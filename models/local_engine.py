"""
models/local_engine.py
로컬 Gemma 3n E2B-it 추론 엔진
- 최초 실행 시 ~6GB 자동 다운로드
- 4bit 양자화 지원 (VRAM ~4GB)
- CPU fallback 지원
"""

from __future__ import annotations

import gc
import json
import os
import re
import time
from typing import Iterator, Optional

import torch

LOCAL_MODEL_ID = "google/gemma-3n-E2B-it"
SYSTEM_KO = (
    "당신은 삼성전자 갤럭시 스마트폰 시니어 제품 기획 전문가입니다. "
    "항상 한국어로 답변하세요. 분석은 구체적이고 실용적으로 작성하세요."
)


class LocalEngine:
    """로컬 모델 싱글톤 엔진"""

    _inst: Optional["LocalEngine"] = None

    def __new__(cls) -> "LocalEngine":
        if cls._inst is None:
            cls._inst = super().__new__(cls)
            cls._inst._model     = None
            cls._inst._processor = None
            cls._inst._loaded    = False
            cls._inst._model_id  = LOCAL_MODEL_ID
        return cls._inst

    def load(
        self,
        hf_token:    str,
        use_4bit:    bool = True,
        use_gpu:     bool = True,
        progress_cb: Optional[callable] = None,
    ) -> None:
        if self._loaded:
            return

        from transformers import (
            AutoProcessor,
            Gemma3nForConditionalGeneration,
            BitsAndBytesConfig,
        )

        def _cb(msg: str) -> None:
            if progress_cb:
                progress_cb(msg)

        _cb("프로세서 로딩 중…")
        self._processor = AutoProcessor.from_pretrained(
            LOCAL_MODEL_ID, token=hf_token, trust_remote_code=True
        )

        _cb("모델 가중치 로딩 중… (최초 실행 시 ~6GB 다운로드)")
        has_cuda   = torch.cuda.is_available()
        device_map = "auto" if (use_gpu and has_cuda) else "cpu"

        kwargs: dict = {"token": hf_token, "trust_remote_code": True}

        if use_4bit and has_cuda:
            kwargs["quantization_config"] = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_compute_dtype=torch.bfloat16,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_use_double_quant=True,
            )
            kwargs["device_map"] = device_map
        elif has_cuda:
            kwargs["torch_dtype"]  = torch.bfloat16
            kwargs["device_map"]   = device_map
        else:
            kwargs["torch_dtype"]  = torch.float32
            kwargs["device_map"]   = "cpu"

        self._model = Gemma3nForConditionalGeneration.from_pretrained(
            LOCAL_MODEL_ID, **kwargs
        ).eval()
        self._loaded = True

        if has_cuda:
            used  = torch.cuda.memory_allocated() / 1024**3
            total = torch.cuda.get_device_properties(0).total_memory / 1024**3
            _cb(f"✅ 로드 완료  VRAM {used:.1f}/{total:.1f}GB")
        else:
            _cb("✅ 로드 완료 (CPU 모드)")

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def model_id(self) -> str:
        return self._model_id

    def generate(
        self,
        prompt:      str,
        system:      str   = SYSTEM_KO,
        max_tokens:  int   = 2048,
        temperature: float = 0.3,
        do_sample:   bool  = True,
    ) -> str:
        if not self._loaded:
            raise RuntimeError("모델이 로드되지 않았습니다.")

        messages = [{
            "role": "user",
            "content": [{"type": "text", "text": f"{system}\n\n{prompt}"}],
        }]
        inputs = self._processor.apply_chat_template(
            messages, add_generation_prompt=True,
            tokenize=True, return_dict=True, return_tensors="pt",
        )
        device = next(self._model.parameters()).device
        inputs = {k: v.to(device) for k, v in inputs.items() if isinstance(v, torch.Tensor)}
        in_len = inputs["input_ids"].shape[-1]

        kwargs: dict = dict(
            **inputs,
            max_new_tokens=max_tokens,
            do_sample=do_sample,
            pad_token_id=self._processor.tokenizer.eos_token_id,
        )
        if do_sample:
            kwargs.update(temperature=temperature, top_p=0.9)

        with torch.inference_mode():
            out = self._model.generate(**kwargs)

        return self._processor.decode(out[0][in_len:], skip_special_tokens=True)

    def generate_stream(
        self,
        prompt:      str,
        system:      str   = SYSTEM_KO,
        max_tokens:  int   = 3000,
        temperature: float = 0.25,
    ) -> Iterator[str]:
        from transformers import TextIteratorStreamer
        import threading

        messages = [{
            "role": "user",
            "content": [{"type": "text", "text": f"{system}\n\n{prompt}"}],
        }]
        inputs = self._processor.apply_chat_template(
            messages, add_generation_prompt=True,
            tokenize=True, return_dict=True, return_tensors="pt",
        )
        device = next(self._model.parameters()).device
        inputs = {k: v.to(device) for k, v in inputs.items() if isinstance(v, torch.Tensor)}

        streamer = TextIteratorStreamer(
            self._processor.tokenizer,
            skip_prompt=True, skip_special_tokens=True,
        )
        kwargs = dict(
            **inputs, max_new_tokens=max_tokens,
            do_sample=True, temperature=temperature, top_p=0.9,
            pad_token_id=self._processor.tokenizer.eos_token_id,
            streamer=streamer,
        )
        t = threading.Thread(target=self._model.generate, kwargs=kwargs)
        t.start()
        for text in streamer:
            yield text
        t.join()

    def unload(self) -> None:
        del self._model, self._processor
        self._model = self._processor = None
        self._loaded = False
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


local_engine = LocalEngine()


def analyze_voc_local(voc_list: list, model_info_str: str = "갤럭시") -> dict:
    grouped: dict = {}
    for v in voc_list:
        cat = v.category if hasattr(v, "category") else v.get("category", "기타")
        ttl = v.title    if hasattr(v, "title")    else v.get("title", "")
        grouped.setdefault(cat, []).append(ttl)

    summary = "\n\n".join(
        f"[{cat}] ({len(ts)}건)\n" + "\n".join(f"  • {t}" for t in ts[:8])
        for cat, ts in sorted(grouped.items(), key=lambda x: -len(x[1]))
    )

    prompt = f"""아래는 {model_info_str} VOC 데이터 {len(voc_list)}건입니다.

{summary}

아래 JSON 형식으로만 응답하세요:

{{
  "executive_summary": "핵심 요약 3-4문장",
  "critical_issues": [{{"title":"","description":"","frequency":"높음/중간/낮음","impact":"높음/중간/낮음","category":""}}],
  "requirements": [{{"id":"REQ-001","category":"","priority":"필수/권장/선택","title":"","description":"","user_story":"","acceptance_criteria":[]}}],
  "roadmap": [{{"phase":"즉시(1개월)","items":[]}},{{"phase":"단기(1-3개월)","items":[]}},{{"phase":"중기(3-6개월)","items":[]}},{{"phase":"장기(6개월+)","items":[]}}],
  "key_insights": []
}}"""

    raw = local_engine.generate(prompt, max_tokens=3000, temperature=0.2)
    try:
        m = re.search(r"\{[\s\S]*\}", raw)
        if m:
            return json.loads(m.group())
    except Exception:
        pass
    return {
        "executive_summary": raw[:400],
        "critical_issues": [], "requirements": [],
        "roadmap": [], "key_insights": [],
    }
