"""Shape database rows into API views: golden records with provenance, masked contact data."""

from __future__ import annotations

from typing import Any

from leadintel.security.authz import Permission, Principal, mask_email, mask_phone
from leadintel.security.crypto import FieldCipher


def attribute_view(golden: dict[str, Any]) -> dict[str, Any]:
    """``{attr: {value, source, observed_at, confidence, agreeing_sources, alternatives}}``."""
    view: dict[str, Any] = {}
    for name, attr in sorted(golden.items()):
        provenance = attr.get("provenance") or {}
        view[name] = {
            "value": attr.get("value"),
            "source": provenance.get("source"),
            "observed_at": provenance.get("observed_at"),
            "record_id": provenance.get("source_record_id"),
            "confidence": attr.get("confidence"),
            "agreeing_sources": attr.get("agreeing_sources", 1),
            "alternatives": [
                {
                    "value": alt.get("value"),
                    "source": (alt.get("provenance") or {}).get("source"),
                    "observed_at": (alt.get("provenance") or {}).get("observed_at"),
                }
                for alt in attr.get("alternatives") or []
            ],
        }
    return view


def contact_view(
    row: dict[str, Any], principal: Principal, cipher: FieldCipher
) -> dict[str, Any] | None:
    """Contact details: decrypted for ``pii:read`` holders (caller audits), masked otherwise."""
    envelope = row.get("pii_envelope")
    if not envelope:
        return None
    restricted = cipher.decrypt_json(bytes(envelope))
    if principal.has(Permission.PII_READ):
        return {"email": restricted.get("email"), "phone": restricted.get("phone"), "masked": False}
    return {
        "email": mask_email(restricted.get("email")),
        "phone": mask_phone(restricted.get("phone")),
        "masked": True,
    }


def entity_view(row: dict[str, Any], *, contact: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "type": row["entity_type"],
        "display_name": row["display_name"],
        "status": row["status"],
        "merged_into": str(row["merged_into"]) if row.get("merged_into") else None,
        "domain": row.get("primary_domain"),
        "attributes": attribute_view(row.get("golden") or {}),
        "contact": contact,
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
    }


def lineage_view(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "record_id": str(r["record_id"]),
            "source": r["source"],
            "observed_at": r["observed_at"].isoformat(),
            "fetched_at": r["fetched_at"].isoformat(),
            "source_url": r["source_url"],
            "lawful_basis": r["lawful_basis"],
            "match": {
                "method": r["method"],
                "probability": float(r["match_probability"]),
                "evidence": r["evidence"],
                "decided_by": r["decided_by"],
            },
        }
        for r in rows
    ]


def signal_view(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "type": row["signal_type"],
        "source": row["source"],
        "occurred_at": row["occurred_at"].isoformat(),
        "title": row["title"],
        "url": row["url"],
        "strength": float(row["strength"]),
        "entity_id": str(row["entity_id"]) if row.get("entity_id") else None,
    }


def graph_view(graph: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    return {
        "nodes": [
            {
                "id": str(n["id"]),
                "type": n["entity_type"],
                "label": n["display_name"] or n["primary_domain"],
            }
            for n in graph["nodes"]
        ],
        "edges": [
            {
                "id": str(e["id"]),
                "source": str(e["src_entity_id"]),
                "target": str(e["dst_entity_id"]),
                "type": e["rel_type"],
                "properties": e["properties"],
                "provenance": e["source"],
                "confidence": float(e["confidence"]),
            }
            for e in graph["edges"]
        ],
    }


def lead_summary(row: dict[str, Any]) -> dict[str, Any]:
    def num(value: Any) -> float | None:
        return float(value) if value is not None else None

    return {
        "id": str(row["id"]),
        "status": row["status"],
        "tier": row["tier"],
        "score": num(row["score"]),
        "fit": num(row["fit_score"]),
        "intent": num(row["intent_score"]),
        "engagement": num(row["engagement_score"]),
        "hot": row["hot"],
        "scored_at": row["scored_at"].isoformat() if row.get("scored_at") else None,
        "organization": {
            "id": str(row["organization_id"]) if row.get("organization_id") else None,
            "name": row.get("organization_name"),
            "domain": row.get("organization_domain"),
            "industry": row.get("industry"),
            "country": row.get("hq_country"),
            "employees": row.get("employee_count"),
        },
        "person": {
            "id": str(row["person_id"]),
            "name": row.get("person_name"),
            "title": row.get("person_title"),
        }
        if row.get("person_id")
        else None,
        "last_signal_at": row["last_signal_at"].isoformat() if row.get("last_signal_at") else None,
    }
