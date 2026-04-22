from __future__ import annotations

from typing import Any


def filter_search_result_card(card_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
    note_list: list[dict[str, Any]] = []
    for card_item in card_list:
        if card_item.get("card_type") == 9:
            note_list.append(card_item)
        for card_group_item in card_item.get("card_group", []) or []:
            if card_group_item.get("card_type") == 9:
                note_list.append(card_group_item)
    return note_list
