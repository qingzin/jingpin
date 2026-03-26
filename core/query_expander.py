"""
query_expander.py
面向中文检索的轻量术语扩展：
- 用户只输入中文
- 数据里可能是中文、英文或中英混杂
"""

TERM_GROUPS = [
    ["仪表盘", "仪表板", "dashboard", "instrument panel", "ip"],
    ["引擎盖", "发动机盖", "hood", "bonnet"],
    ["铰链", "hinge"],
    ["支架", "bracket", "mount", "support"],
    ["加强板", "reinforcement", "reinforcement plate", "stiffener"],
    ["固定件", "fastener", "fixing", "retainer"],
    ["卡扣", "clip", "retainer"],
    ["密封条", "seal", "weatherstrip"],
    ["门板", "door panel", "trim panel"],
    ["门槛", "sill", "rocker"],
    ["横梁", "beam", "cross member", "crossmember"],
    ["护板", "shield", "guard", "undercover"],
    ["前门", "front door"],
    ["后门", "rear door"],
    ["前舱", "front compartment", "frunk", "front cabin"],
    ["后舱", "rear compartment", "trunk", "cargo"],
    ["左", "left", "lh"],
    ["右", "right", "rh"],
    ["前", "front", "fr"],
    ["后", "rear", "rr"],
    ["总成", "assembly", "assy"],
    ["钢", "steel"],
    ["铝", "aluminum", "aluminium"],
    ["塑料", "plastic"],
    ["橡胶", "rubber"],
    ["泡沫", "foam"],
    ["电泳", "e-coat", "ecoat", "electrophoresis"],
    ["喷涂", "coating", "paint"],
    ["镀锌", "galvanized", "galvanized steel"],
]


def expand_text_query(text: str) -> str:
    """
    将中文查询补成“中文 + 常见英文别名”的语义文本。
    """
    text = (text or "").strip()
    if not text:
        return text

    extras = []
    lower_text = text.lower()
    for group in TERM_GROUPS:
        if any(term.lower() in lower_text for term in group):
            for term in group:
                if term.lower() not in lower_text:
                    extras.append(term)

    if not extras:
        return text
    return f"{text} | {' | '.join(dict.fromkeys(extras))}"


def expand_filter_values(value: str) -> list[str]:
    """
    文本过滤值扩展成中英同义词集合。
    """
    value = (value or "").strip()
    if not value:
        return []

    lower_value = value.lower()
    expanded = [value]
    for group in TERM_GROUPS:
        if any(term.lower() in lower_value or lower_value in term.lower() for term in group):
            expanded.extend(group)

    return list(dict.fromkeys(v for v in expanded if v))
