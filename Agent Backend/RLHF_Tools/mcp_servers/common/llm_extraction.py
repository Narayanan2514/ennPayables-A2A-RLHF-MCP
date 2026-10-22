"""Vision-LLM field extraction with self-consistency confidence scoring.

ennvault-existing's extractors (modules/processing/entity_extractor/llm_service/
*_extract.py) call langchain_openai.ChatOpenAI(model="gpt-4o", temperature=0)
once per document and trust the result outright -- "no confidence scores
anywhere" (audit section 4/13). Per the proposal's Section 4.1
(Confidence-Aware Routing), this module keeps the same proven GPT-4o vision
approach (same model, same base64-image-block calling convention) but samples
it N times at temperature>0 and derives a per-field confidence from
self-consistency (agreement rate across samples) -- one of the three
confidence sources the proposal names explicitly (log-probs, self-consistency,
or a calibration model trained on correction history).

This intentionally does NOT reuse ennvault-existing's code directly (that
codebase is not to be modified or imported from), it re-implements the same
calling pattern fresh.
"""
from __future__ import annotations

import base64
import json
import os
from collections import Counter
from dataclasses import dataclass, field

import pymupdf
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from config.settings import get_settings

# Render resolution for PDF -> PNG conversion. 200 DPI is the usual sweet
# spot for OCR/vision-model legibility on invoice-sized text without
# ballooning the base64 payload.
_PDF_RENDER_DPI = 200


def _get_llm(temperature: float) -> ChatOpenAI:
    settings = get_settings()
    return ChatOpenAI(
        model=settings.openai_vision_model,
        temperature=temperature,
        api_key=settings.openai_api_key or None,
    )


def encode_image_b64(image_path: str) -> str:
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _image_content_block(image_path: str) -> dict:
    b64 = encode_image_b64(image_path)
    ext = image_path.rsplit(".", 1)[-1].lower()
    mime = "image/png" if ext == "png" else "image/jpeg"
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}


def _pdf_page_content_blocks(pdf_path: str) -> list[dict]:
    """The vision API only accepts png/jpeg/gif/webp, but real invoices
    routinely arrive as PDFs (see get_source's atch_nm) -- render each page
    to a PNG in-memory instead of sending unsupported bytes straight through
    and failing with invalid_image_format.
    """
    blocks = []
    with pymupdf.open(pdf_path) as doc:
        matrix = pymupdf.Matrix(_PDF_RENDER_DPI / 72, _PDF_RENDER_DPI / 72)
        for page in doc:
            png_bytes = page.get_pixmap(matrix=matrix).tobytes("png")
            b64 = base64.b64encode(png_bytes).decode("utf-8")
            blocks.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}})
    return blocks


def _content_blocks_for_path(path: str) -> list[dict]:
    if os.path.isdir(path):
        # Callers sometimes hand us the upload folder itself (see
        # email_module/service.py's per-message "upload_<timestamp>" dirs)
        # rather than the file(s) inside it -- expand it instead of failing.
        blocks = []
        for name in sorted(os.listdir(path)):
            blocks.extend(_content_blocks_for_path(os.path.join(path, name)))
        return blocks
    if path.rsplit(".", 1)[-1].lower() == "pdf":
        return _pdf_page_content_blocks(path)
    return [_image_content_block(path)]


def _parse_json_response(raw: str) -> dict:
    """More forgiving than ennvault-existing's bare `.strip('```json').strip('```')`
    (audit §4 flags this as fragile against any leading/trailing text around
    the fences). Finds the first `{`/last `}` pair as a fallback.
    """
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[len("json") :]
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1:
            raise
        return json.loads(text[start : end + 1])


def call_vision_llm_once(system_prompt: str, image_paths: list[str], temperature: float) -> dict:
    llm = _get_llm(temperature)
    content_blocks = [{"type": "text", "text": "Extract the fields described in the system prompt as JSON."}]
    content_blocks.extend(block for p in image_paths for block in _content_blocks_for_path(p))
    messages = [SystemMessage(content=system_prompt), HumanMessage(content=content_blocks)]
    response = llm.invoke(messages)
    return _parse_json_response(response.content)


@dataclass
class ExtractionResult:
    fields: dict
    field_confidence: dict[str, float] = field(default_factory=dict)
    overall_confidence: float = 0.0
    raw_samples: list[dict] = field(default_factory=list)


def _flatten_scalar_fields(d: dict, prefix: str = "") -> dict:
    """Flattens a header-shaped dict (skips list-valued keys like line items,
    which are compared separately) so per-field agreement can be computed.
    """
    flat = {}
    for k, v in d.items():
        if isinstance(v, (dict, list)):
            continue
        flat[f"{prefix}{k}"] = v
    return flat


def extract_with_confidence(
    system_prompt: str,
    image_paths: list[str],
    n_samples: int = 3,
    sampling_temperature: float = 0.4,
) -> ExtractionResult:
    """Runs the extraction n_samples times and derives per-field confidence
    from how often samples agree on each field's value (majority vote wins).
    A single deterministic call (temperature=0) is included as one of the
    samples so the "obvious" answer is always represented.
    """
    samples = [call_vision_llm_once(system_prompt, image_paths, temperature=0.0)]
    samples.extend(
        call_vision_llm_once(system_prompt, image_paths, temperature=sampling_temperature)
        for _ in range(max(0, n_samples - 1))
    )

    flat_samples = [_flatten_scalar_fields(s) for s in samples]
    all_keys = set().union(*flat_samples) if flat_samples else set()

    majority_fields: dict = {}
    field_confidence: dict[str, float] = {}
    for key in all_keys:
        values = [s.get(key) for s in flat_samples if key in s]
        if not values:
            continue
        counts = Counter(str(v) for v in values)
        top_value_str, top_count = counts.most_common(1)[0]
        # Map the winning stringified value back to its first original (typed) value
        winning_value = next(v for v in values if str(v) == top_value_str)
        majority_fields[key] = winning_value
        field_confidence[key] = top_count / len(values)

    # Preserve any non-scalar fields (e.g. line items) from the deterministic
    # (temperature=0) sample untouched -- confidence scoring for line-item
    # arrays is out of scope here; routing should treat those as unscored.
    for key, value in samples[0].items():
        if key not in majority_fields:
            majority_fields[key] = value

    overall_confidence = (
        sum(field_confidence.values()) / len(field_confidence) if field_confidence else 0.0
    )

    return ExtractionResult(
        fields=majority_fields,
        field_confidence=field_confidence,
        overall_confidence=round(overall_confidence, 4),
        raw_samples=samples,
    )
