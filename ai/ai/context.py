"""Общий контекст анализа: документы и сборка Evidence из ответов LLM."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pydantic import BaseModel

from .parsing import render_for_prompt
from .schemas import DocumentText, Evidence, Side


class LLMEvidence(BaseModel):
    """Ссылка на источник в том виде, в котором её возвращает LLM."""

    doc_id: str
    clause_id: str
    quote: str


@dataclass
class Ctx:
    docs: list[DocumentText]
    by_id: dict[str, DocumentText] = field(init=False)

    def __post_init__(self) -> None:
        self.by_id = {d.doc_id: d for d in self.docs}

    def side(self, side: Side) -> list[DocumentText]:
        return [d for d in self.docs if d.side == side]

    def render(self, side: Side | None = None, sections: set[str] | None = None) -> str:
        docs = self.docs if side is None else self.side(side)
        return "\n\n".join(render_for_prompt(d, sections) for d in docs)

    def evidence(self, items: list[LLMEvidence]) -> list[Evidence]:
        """LLM-ссылки → Evidence. Ссылки на несуществующие документы/пункты отбрасываются;
        цитаты окончательно проверяет evidence.verify_result."""
        out: list[Evidence] = []
        for it in items:
            doc = self.by_id.get(it.doc_id.strip())
            cid = normalize_clause_id(it.clause_id)
            if doc is None or not it.quote.strip():
                continue
            if not any(c.clause_id == cid for c in doc.clauses):
                continue
            out.append(Evidence(doc_id=doc.doc_id, doc_name=doc.name, side=doc.side,
                                clause_id=cid, quote=it.quote.strip()))
        return out


_LATIN_TO_CYR = str.maketrans({"a": "а", "b": "б", "c": "с", "e": "е"})


def normalize_clause_id(cid: str) -> str:
    """'[3.4.а]', 'п. 3.4.а', '3.4.а.' → '3.4.а'."""
    cid = cid.strip().strip("[]").strip()
    cid = re.sub(r"^(п\.|пункт)\s*", "", cid, flags=re.I).strip().rstrip(".")
    # латинские буквы-двойники в подпунктах: 3.4.a → 3.4.а
    return re.sub(r"\.([a-z])$", lambda m: "." + m.group(1).translate(_LATIN_TO_CYR), cid)
