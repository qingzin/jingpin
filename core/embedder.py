"""
embedder.py
调用内网 BGE-M3 API 生成向量。
API endpoint: https://aiservice.byd.com/yicellm-api/v1
兼容 OpenAI embeddings 接口格式。
"""
import os
import time
import logging
from typing import Optional
import requests

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# 配置
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_API_BASE   = "https://aiservice.byd.com/yicellm-api/v1"
DEFAULT_MODEL      = "bge-m3"
DEFAULT_BATCH_SIZE = 32        # 每批发送条数，避免请求过大
DEFAULT_MAX_RETRY  = 3
DEFAULT_RETRY_WAIT = 2.0       # 秒

PAYLOAD_FIELDS = [
    "source_file", "source_row", "part_name", "part_number",
    "level_array", "level_depth", "form",
    "manufacturer", "material", "material_code", "material_type",
    "material_grade", "surface_treat", "process",
    "weight_kg", "total_weight_kg", "quantity",
    "width_mm", "height_mm", "depth_mm", "length_mm",
    "thickness_mm", "diameter_mm",
    "location", "detail", "remarks", "aux_name", "part_type",
    "system", "assembly_teardown", "site",
    "vehicle_model",
]


# ─────────────────────────────────────────────────────────────────────────────
# Embedding 文本构建
# ─────────────────────────────────────────────────────────────────────────────

def build_embedding_text(row: dict) -> str:
    """
    只拼接适合做语义召回的“名词/结构”字段。
    精准过滤属性（车型、编号、材料、供应商、重量尺寸等）不放进 embedding，
    避免向量语义空间被过滤字段污染。

    示例输出：
    "前左门密封条 | 密封条 | 车身系统 > 车门总成 > 前左门 > 密封条 | 车门区域"
    """
    level_array = row.get("_level_array") or []
    level_path  = " > ".join(level_array) if level_array else ""

    def _str(val) -> str:
        if val is None:
            return ""
        import math
        if isinstance(val, float) and math.isnan(val):
            return ""
        return str(val).strip()

    segments = [
        _str(row.get("_part_name") or row.get("part_name")),
        _str(row.get("aux_name")),
        _str(row.get("part_type")),
        level_path,
        _str(row.get("system")),
        _str(row.get("location")),
        _str(row.get("detail")),
        _str(row.get("left_desc")),
        _str(row.get("right_desc")),
        _str(row.get("rear_desc")),
    ]
    text = " | ".join(s for s in segments if s)
    return text or "unknown"


def build_qdrant_payload(row: dict) -> dict:
    """
    构造用于 Qdrant 过滤和结果展示的轻量 payload。

    约定：
      - vehicle_name: 实际车型/拆解对象，优先使用 source_file
      - borrowed_vehicle_model: 表格内的借用车型/车型编号等原始字段，保留但不再混充车型名
    """
    level_array = _normalize_level_array(row.get("level_array"))
    if not level_array:
        level_array = _normalize_level_array(row.get("_level_array"))
    level_path = " > ".join(level_array) if isinstance(level_array, list) and level_array else None
    source_file = _clean_payload_value(row.get("source_file"))
    vehicle_name = source_file or _clean_payload_value(row.get("vehicle_name"))

    payload = {
        "vehicle_name": vehicle_name,
        "source_file": source_file,
        "source_row": _clean_payload_value(row.get("source_row")),
        "part_name": _clean_payload_value(row.get("_part_name") or row.get("part_name")),
        "part_number": _clean_payload_value(row.get("part_number")),
        "level_path": level_path,
        "level_array": level_array if level_path else None,
        "level_depth": _clean_payload_value(row.get("level_depth") or (len(level_array) if isinstance(level_array, list) else None)),
        "form": _clean_payload_value(row.get("form") or row.get("_form")),
        "manufacturer": _clean_payload_value(row.get("manufacturer")),
        "material": _clean_payload_value(row.get("material")),
        "material_code": _clean_payload_value(row.get("material_code")),
        "material_type": _clean_payload_value(row.get("material_type")),
        "material_grade": _clean_payload_value(row.get("material_grade")),
        "surface_treat": _clean_payload_value(row.get("surface_treat")),
        "process": _clean_payload_value(row.get("process")),
        "weight_kg": _clean_payload_value(row.get("weight_kg")),
        "total_weight_kg": _clean_payload_value(row.get("total_weight_kg")),
        "quantity": _clean_payload_value(row.get("quantity")),
        "width_mm": _clean_payload_value(row.get("width_mm")),
        "height_mm": _clean_payload_value(row.get("height_mm")),
        "depth_mm": _clean_payload_value(row.get("depth_mm")),
        "length_mm": _clean_payload_value(row.get("length_mm")),
        "thickness_mm": _clean_payload_value(row.get("thickness_mm")),
        "diameter_mm": _clean_payload_value(row.get("diameter_mm")),
        "location": _clean_payload_value(row.get("location")),
        "detail": _clean_payload_value(row.get("detail")),
        "remarks": _clean_payload_value(row.get("remarks")),
        "aux_name": _clean_payload_value(row.get("aux_name")),
        "part_type": _clean_payload_value(row.get("part_type")),
        "system": _clean_payload_value(row.get("system")),
        "assembly_teardown": _clean_payload_value(row.get("assembly_teardown")),
        "site": _clean_payload_value(row.get("site")),
        "borrowed_vehicle_model": _clean_payload_value(row.get("vehicle_model")),
    }
    return {k: v for k, v in payload.items() if v not in (None, "", [], {})}


def _clean_payload_value(val):
    if val is None:
        return None
    if isinstance(val, float):
        try:
            import math
            if math.isnan(val):
                return None
        except TypeError:
            pass
    if isinstance(val, str):
        val = val.strip()
        return val or None
    return val


def _normalize_level_array(val):
    if val is None:
        return []
    if isinstance(val, list):
        return val
    if isinstance(val, tuple):
        return list(val)
    if hasattr(val, "tolist"):
        converted = val.tolist()
        if isinstance(converted, list):
            return converted
    return []


# ─────────────────────────────────────────────────────────────────────────────
# API 客户端
# ─────────────────────────────────────────────────────────────────────────────

class BGEEmbedder:
    """
    调用内网 BGE-M3 API 的 Embedding 客户端。

    使用方式：
        # 方式1：直接传入 token
        embedder = BGEEmbedder(api_key="your_bearer_token")

        # 方式2：通过环境变量 BGE_API_KEY
        # Windows PowerShell: $env:BGE_API_KEY="your_bearer_token"
        # Windows CMD:        set BGE_API_KEY=your_bearer_token
        embedder = BGEEmbedder()

        vectors = embedder.embed(["零件名称1", "零件名称2"])
    """

    def __init__(
        self,
        api_key:    Optional[str] = None,
        api_base:   str = DEFAULT_API_BASE,
        model:      str = DEFAULT_MODEL,
        batch_size: int = DEFAULT_BATCH_SIZE,
        max_retry:  int = DEFAULT_MAX_RETRY,
        retry_wait: float = DEFAULT_RETRY_WAIT,
        timeout:    int = 60,
    ):
        self.api_key    = api_key or os.environ.get("BGE_API_KEY", "")
        self.api_base   = api_base.rstrip("/")
        self.model      = model
        self.batch_size = batch_size
        self.max_retry  = max_retry
        self.retry_wait = retry_wait
        self.timeout    = timeout

        if not self.api_key:
            raise ValueError(
                "未找到 BGE API Key。\n"
                "请通过以下方式之一提供：\n"
                "  1. BGEEmbedder(api_key='your_token')\n"
                "  2. 环境变量 BGE_API_KEY（例如 PowerShell: $env:BGE_API_KEY='your_token'）"
            )

        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type":  "application/json",
        })

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        """单批次 embedding，带重试"""
        url     = f"{self.api_base}/embeddings"
        payload = {"model": self.model, "input": texts}

        for attempt in range(1, self.max_retry + 1):
            try:
                resp = self._session.post(url, json=payload, timeout=self.timeout)
                resp.raise_for_status()
                data = resp.json()
                # 兼容 OpenAI 格式：data.data[].embedding
                return [item["embedding"] for item in data["data"]]
            except requests.HTTPError as e:
                logger.warning(f"HTTP 错误 (尝试 {attempt}/{self.max_retry}): {e}")
                if attempt == self.max_retry:
                    raise
            except requests.RequestException as e:
                logger.warning(f"请求失败 (尝试 {attempt}/{self.max_retry}): {e}")
                if attempt == self.max_retry:
                    raise
            time.sleep(self.retry_wait * attempt)

    def embed(self, texts: list[str]) -> list[list[float]]:
        """
        对文本列表批量生成 embedding。
        自动分批，返回与输入等长的向量列表。
        """
        if not texts:
            return []

        all_vectors = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i: i + self.batch_size]
            vectors = self._embed_batch(batch)
            all_vectors.extend(vectors)
            logger.debug(f"Embedding 进度: {min(i + self.batch_size, len(texts))}/{len(texts)}")

        return all_vectors

    def embed_single(self, text: str) -> list[float]:
        """对单条文本生成 embedding（用于检索时的 query 编码）"""
        return self.embed([text])[0]

    def get_dimension(self) -> int:
        """探测向量维度（通过发送一条测试文本）"""
        vec = self.embed_single("test")
        return len(vec)
