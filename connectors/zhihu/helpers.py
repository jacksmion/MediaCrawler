from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import execjs
from parsel import Selector

from . import constants as zhihu_constant
from .models import ZhihuComment, ZhihuContent, ZhihuCreator
from tools import utils
from tools.crawler_util import extract_text_from_html

ZHIHU_SIGN_JS = None


def sign(url: str, cookies: str) -> dict[str, Any]:
    global ZHIHU_SIGN_JS
    if not ZHIHU_SIGN_JS:
        script_path = Path(__file__).resolve().parents[2] / "libs" / "zhihu.js"
        ZHIHU_SIGN_JS = execjs.compile(script_path.read_text(encoding="utf-8-sig"))
    return ZHIHU_SIGN_JS.call("get_sign", url, cookies)


class ZhihuExtractor:
    def extract_contents_from_search(self, json_data: dict[str, Any]) -> list[ZhihuContent]:
        if not json_data:
            return []
        search_result = json_data.get("data", [])
        search_result = [item for item in search_result if item.get("type") in ["search_result", "zvideo"]]
        return self._extract_content_list([item.get("object") for item in search_result if item.get("object")])

    def _extract_content_list(self, content_list: list[dict[str, Any]]) -> list[ZhihuContent]:
        if not content_list:
            return []
        result: list[ZhihuContent] = []
        for content in content_list:
            if content.get("type") == zhihu_constant.ANSWER_NAME:
                result.append(self._extract_answer_content(content))
            elif content.get("type") == zhihu_constant.ARTICLE_NAME:
                result.append(self._extract_article_content(content))
            elif content.get("type") == zhihu_constant.VIDEO_NAME:
                result.append(self._extract_zvideo_content(content))
        return result

    def _extract_answer_content(self, answer: dict[str, Any]) -> ZhihuContent:
        res = ZhihuContent()
        res.content_id = answer.get("id")
        res.content_type = answer.get("type")
        res.content_text = extract_text_from_html(answer.get("content", ""))
        res.question_id = answer.get("question").get("id")
        res.content_url = f"{zhihu_constant.ZHIHU_URL}/question/{res.question_id}/answer/{res.content_id}"
        res.title = extract_text_from_html(answer.get("title", ""))
        res.desc = extract_text_from_html(answer.get("description", "") or answer.get("excerpt", ""))
        res.created_time = answer.get("created_time")
        res.updated_time = answer.get("updated_time")
        res.voteup_count = answer.get("voteup_count", 0)
        res.comment_count = answer.get("comment_count", 0)
        author_info = self._extract_content_or_comment_author(answer.get("author"))
        res.user_id = author_info.user_id
        res.user_link = author_info.user_link
        res.user_nickname = author_info.user_nickname
        res.user_avatar = author_info.user_avatar
        res.user_url_token = author_info.url_token
        return res

    def _extract_article_content(self, article: dict[str, Any]) -> ZhihuContent:
        res = ZhihuContent()
        res.content_id = article.get("id")
        res.content_type = article.get("type")
        res.content_text = extract_text_from_html(article.get("content"))
        res.content_url = f"{zhihu_constant.ZHIHU_ZHUANLAN_URL}/p/{res.content_id}"
        res.title = extract_text_from_html(article.get("title"))
        res.desc = extract_text_from_html(article.get("excerpt"))
        res.created_time = article.get("created_time", 0) or article.get("created", 0)
        res.updated_time = article.get("updated_time", 0) or article.get("updated", 0)
        res.voteup_count = article.get("voteup_count", 0)
        res.comment_count = article.get("comment_count", 0)
        author_info = self._extract_content_or_comment_author(article.get("author"))
        res.user_id = author_info.user_id
        res.user_link = author_info.user_link
        res.user_nickname = author_info.user_nickname
        res.user_avatar = author_info.user_avatar
        res.user_url_token = author_info.url_token
        return res

    def _extract_zvideo_content(self, zvideo: dict[str, Any]) -> ZhihuContent:
        res = ZhihuContent()
        if "video" in zvideo and isinstance(zvideo.get("video"), dict):
            res.content_url = f"{zhihu_constant.ZHIHU_URL}/zvideo/{res.content_id}"
            res.created_time = zvideo.get("published_at")
            res.updated_time = zvideo.get("updated_at")
        else:
            res.content_url = zvideo.get("video_url")
            res.created_time = zvideo.get("created_at")
        res.content_id = zvideo.get("id")
        res.content_type = zvideo.get("type")
        res.title = extract_text_from_html(zvideo.get("title"))
        res.desc = extract_text_from_html(zvideo.get("description"))
        res.voteup_count = zvideo.get("voteup_count")
        res.comment_count = zvideo.get("comment_count")
        author_info = self._extract_content_or_comment_author(zvideo.get("author"))
        res.user_id = author_info.user_id
        res.user_link = author_info.user_link
        res.user_nickname = author_info.user_nickname
        res.user_avatar = author_info.user_avatar
        res.user_url_token = author_info.url_token
        return res

    @staticmethod
    def _extract_content_or_comment_author(author: dict[str, Any] | None) -> ZhihuCreator:
        res = ZhihuCreator()
        try:
            if not author:
                return res
            if not author.get("id"):
                author = author.get("member")
            res.user_id = author.get("id")
            res.user_link = f"{zhihu_constant.ZHIHU_URL}/people/{author.get('url_token')}"
            res.user_nickname = author.get("name")
            res.user_avatar = author.get("avatar_url")
            res.url_token = author.get("url_token")
        except Exception as exc:
            utils.logger.warning(f"[ZhihuExtractor._extract_content_or_comment_author] User Maybe Blocked. {exc}")
        return res

    def extract_comments(self, page_content: ZhihuContent, comments: list[dict[str, Any]]) -> list[ZhihuComment]:
        if not comments:
            return []
        return [self._extract_comment(page_content, comment) for comment in comments if comment.get("type") == "comment"]

    def _extract_comment(self, page_content: ZhihuContent, comment: dict[str, Any]) -> ZhihuComment:
        res = ZhihuComment()
        res.comment_id = str(comment.get("id", ""))
        res.parent_comment_id = comment.get("reply_comment_id")
        res.content = extract_text_from_html(comment.get("content"))
        res.publish_time = comment.get("created_time")
        res.ip_location = self._extract_comment_ip_location(comment.get("comment_tag", []))
        res.sub_comment_count = comment.get("child_comment_count")
        res.like_count = comment.get("like_count") if comment.get("like_count") else 0
        res.dislike_count = comment.get("dislike_count") if comment.get("dislike_count") else 0
        res.content_id = page_content.content_id
        res.content_type = page_content.content_type
        author_info = self._extract_content_or_comment_author(comment.get("author"))
        res.user_id = author_info.user_id
        res.user_link = author_info.user_link
        res.user_nickname = author_info.user_nickname
        res.user_avatar = author_info.user_avatar
        return res

    @staticmethod
    def _extract_comment_ip_location(comment_tags: list[dict[str, Any]]) -> str:
        for tag in comment_tags or []:
            if tag.get("type") == "ip_info":
                return tag.get("text")
        return ""

    @staticmethod
    def extract_offset(paging_info: dict[str, Any]) -> str:
        next_url = paging_info.get("next")
        if not next_url:
            return ""
        parsed_url = urlparse(next_url)
        query_params = parse_qs(parsed_url.query)
        return query_params.get("offset", [""])[0]

    @staticmethod
    def _format_gender_text(gender: int) -> str:
        if gender == 1:
            return "Male"
        if gender == 0:
            return "Female"
        return "Unknown"

    def extract_creator(self, user_url_token: str, html_content: str) -> ZhihuCreator | None:
        if not html_content:
            return None
        js_init_data = Selector(text=html_content).xpath("//script[@id='js-initialData']/text()").get(default="").strip()
        if not js_init_data:
            return None
        js_init_data_dict = json.loads(js_init_data)
        users_info = js_init_data_dict.get("initialState", {}).get("entities", {}).get("users", {})
        creator_info = users_info.get(user_url_token)
        if not creator_info:
            return None
        res = ZhihuCreator()
        res.user_id = creator_info.get("id")
        res.user_link = f"{zhihu_constant.ZHIHU_URL}/people/{user_url_token}"
        res.user_nickname = creator_info.get("name")
        res.user_avatar = creator_info.get("avatarUrl")
        res.url_token = creator_info.get("urlToken") or user_url_token
        res.gender = self._format_gender_text(creator_info.get("gender"))
        res.ip_location = creator_info.get("ipInfo")
        res.follows = creator_info.get("followingCount")
        res.fans = creator_info.get("followerCount")
        res.anwser_count = creator_info.get("answerCount")
        res.video_count = creator_info.get("zvideoCount")
        res.question_count = creator_info.get("questionCount")
        res.article_count = creator_info.get("articlesCount")
        res.column_count = creator_info.get("columnsCount")
        res.get_voteup_count = creator_info.get("voteupCount")
        return res

    def extract_content_list_from_creator(self, answer_list: list[dict[str, Any]]) -> list[ZhihuContent]:
        return self._extract_content_list(answer_list) if answer_list else []

    def extract_answer_content_from_html(self, html_content: str) -> ZhihuContent | None:
        js_init_data = Selector(text=html_content).xpath("//script[@id='js-initialData']/text()").get(default="")
        if not js_init_data:
            return None
        json_data = json.loads(js_init_data)
        answer_info = json_data.get("initialState", {}).get("entities", {}).get("answers", {})
        if not answer_info:
            return None
        return self._extract_answer_content(answer_info.get(list(answer_info.keys())[0]))

    def extract_article_content_from_html(self, html_content: str) -> ZhihuContent | None:
        js_init_data = Selector(text=html_content).xpath("//script[@id='js-initialData']/text()").get(default="")
        if not js_init_data:
            return None
        json_data = json.loads(js_init_data)
        article_info = json_data.get("initialState", {}).get("entities", {}).get("articles", {})
        if not article_info:
            return None
        return self._extract_article_content(article_info.get(list(article_info.keys())[0]))

    def extract_zvideo_content_from_html(self, html_content: str) -> ZhihuContent | None:
        js_init_data = Selector(text=html_content).xpath("//script[@id='js-initialData']/text()").get(default="")
        if not js_init_data:
            return None
        json_data = json.loads(js_init_data)
        zvideo_info = json_data.get("initialState", {}).get("entities", {}).get("zvideos", {})
        users = json_data.get("initialState", {}).get("entities", {}).get("users", {})
        if not zvideo_info:
            return None
        video_detail_info = zvideo_info.get(list(zvideo_info.keys())[0])
        if not video_detail_info:
            return None
        if isinstance(video_detail_info.get("author"), str):
            video_detail_info["author"] = users.get(video_detail_info.get("author"))
        return self._extract_zvideo_content(video_detail_info)


def judge_zhihu_url(note_detail_url: str) -> str:
    if "/answer/" in note_detail_url:
        return zhihu_constant.ANSWER_NAME
    if "/p/" in note_detail_url:
        return zhihu_constant.ARTICLE_NAME
    if "/zvideo/" in note_detail_url:
        return zhihu_constant.VIDEO_NAME
    return ""
