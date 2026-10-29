"""/api/items — the demo resource.

A complete vertical slice: authentication, role checks, rate limiting, caching,
pagination and validation, so each of those has one worked example to copy.
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.auth import require_auth, require_role
from app.services.item_service import ItemService
from app.redis import rate_limit

bp = Blueprint("items", __name__, url_prefix="/api/items")


@bp.get("")
@require_auth
@rate_limit()
def list_items():
    return jsonify(ItemService.list(
        page=request.args.get("page", 1, type=int),
        per_page=request.args.get("per_page", 25, type=int),
        status=request.args.get("status"),
        search=request.args.get("q"),
    ))


@bp.get("/summary")
@require_auth
def summary():
    return jsonify(ItemService.summary())


@bp.get("/<int:item_id>")
@require_auth
def get_item(item_id: int):
    item = ItemService.get(item_id)
    if item is None:
        return jsonify({"error": "Item not found", "status": 404}), 404
    return jsonify(item.to_dict())


@bp.post("")
@require_role("manager")
def create_item():
    item = ItemService.create(request.get_json(silent=True) or {})
    return jsonify(item.to_dict()), 201


@bp.put("/<int:item_id>")
@require_role("manager")
def update_item(item_id: int):
    item = ItemService.get(item_id)
    if item is None:
        return jsonify({"error": "Item not found", "status": 404}), 404
    return jsonify(ItemService.update(item, request.get_json(silent=True) or {}).to_dict())


@bp.delete("/<int:item_id>")
@require_role("admin")
def delete_item(item_id: int):
    item = ItemService.get(item_id)
    if item is None:
        return jsonify({"error": "Item not found", "status": 404}), 404
    ItemService.delete(item)
    return jsonify({"status": "deleted", "id": item_id})
