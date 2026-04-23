from __future__ import annotations

import html
import json
import re
from typing import Any
from urllib.parse import parse_qs, unquote

from parsel import Selector

from . import constants as const
from .models import TiebaComment, TiebaCreator, TiebaNote
from tools import utils

GENDER_MALE = "sex_male"
GENDER_FEMALE = "sex_female"


class TieBaExtractor:
    @staticmethod
    def extract_search_note_list(page_content: str) -> list[TiebaNote]:
        post_list = Selector(text=page_content).xpath("//div[@class='s_post']")
        result: list[TiebaNote] = []
        for post in post_list:
            result.append(
                TiebaNote(
                    note_id=post.xpath(".//span[@class='p_title']/a/@data-tid").get(default="").strip(),
                    title=post.xpath(".//span[@class='p_title']/a/text()").get(default="").strip(),
                    desc=post.xpath(".//div[@class='p_content']/text()").get(default="").strip(),
                    note_url=const.TIEBA_URL + post.xpath(".//span[@class='p_title']/a/@href").get(default=""),
                    user_nickname=post.xpath(".//a[starts-with(@href, '/home/main')]/font/text()").get(default="").strip(),
                    user_link=const.TIEBA_URL + post.xpath(".//a[starts-with(@href, '/home/main')]/@href").get(default=""),
                    tieba_name=post.xpath(".//a[@class='p_forum']/font/text()").get(default="").strip(),
                    tieba_link=const.TIEBA_URL + post.xpath(".//a[@class='p_forum']/@href").get(default=""),
                    publish_time=post.xpath(".//font[@class='p_green p_date']/text()").get(default="").strip(),
                )
            )
        return result

    def extract_tieba_note_list(self, page_content: str) -> list[TiebaNote]:
        content_selector = Selector(text=page_content.replace("<!--", ""))
        post_list = content_selector.xpath("//ul[@id='thread_list']/li")
        result: list[TiebaNote] = []
        for post_selector in post_list:
            post_field_value = self.extract_data_field_value(post_selector)
            if not post_field_value:
                continue
            note_id = str(post_field_value.get("id"))
            result.append(
                TiebaNote(
                    note_id=note_id,
                    title=post_selector.xpath(".//a[@class='j_th_tit ']/text()").get(default="").strip(),
                    desc=post_selector.xpath(".//div[@class='threadlist_abs threadlist_abs_onlyline ']/text()").get(default="").strip(),
                    note_url=f"{const.TIEBA_URL}/p/{note_id}",
                    user_link=const.TIEBA_URL + post_selector.xpath(".//a[@class='frs-author-name j_user_card ']/@href").get(default="").strip(),
                    user_nickname=post_field_value.get("authoer_nickname") or post_field_value.get("author_name"),
                    tieba_name=content_selector.xpath("//a[@class='card_title_fname']/text()").get(default="").strip(),
                    tieba_link=const.TIEBA_URL + content_selector.xpath("//a[@class='card_title_fname']/@href").get(default=""),
                    total_replay_num=post_field_value.get("reply_num", 0),
                )
            )
        return result

    def extract_note_detail(self, page_content: str) -> TiebaNote:
        content_selector = Selector(text=page_content)
        first_floor_selector = content_selector.xpath("//div[@class='p_postlist'][1]")
        only_view_author_link = content_selector.xpath("//*[@id='lzonly_cntn']/@href").get(default="").strip()
        note_id = only_view_author_link.split("?")[0].split("/")[-1]
        thread_num_infos = content_selector.xpath("//div[@id='thread_theme_5']//li[@class='l_reply_num']//span[@class='red']")
        other_info_content = content_selector.xpath(".//div[@class='post-tail-wrap']").get(default="").strip()
        ip_location, publish_time = self.extract_ip_and_pub_time(other_info_content)
        note = TiebaNote(
            note_id=note_id,
            title=content_selector.xpath("//title/text()").get(default="").strip(),
            desc=content_selector.xpath("//meta[@name='description']/@content").get(default="").strip(),
            note_url=f"{const.TIEBA_URL}/p/{note_id}",
            user_link=const.TIEBA_URL + first_floor_selector.xpath(".//a[@class='p_author_face ']/@href").get(default="").strip(),
            user_nickname=first_floor_selector.xpath(".//a[@class='p_author_name j_user_card']/text()").get(default="").strip(),
            user_avatar=first_floor_selector.xpath(".//a[@class='p_author_face ']/img/@src").get(default="").strip(),
            tieba_name=content_selector.xpath("//a[@class='card_title_fname']/text()").get(default="").strip(),
            tieba_link=const.TIEBA_URL + content_selector.xpath("//a[@class='card_title_fname']/@href").get(default=""),
            ip_location=ip_location,
            publish_time=publish_time,
            total_replay_num=thread_num_infos[0].xpath("./text()").get(default="").strip(),
            total_replay_page=thread_num_infos[1].xpath("./text()").get(default="").strip(),
        )
        note.title = note.title.replace(f"【{note.tieba_name}】_Baidu Tieba", "")
        return note

    def extract_tieba_note_parment_comments(self, page_content: str, note_id: str) -> list[TiebaComment]:
        comment_list = Selector(text=page_content).xpath("//div[@class='l_post l_post_bright j_l_post clearfix  ']")
        result: list[TiebaComment] = []
        for comment_selector in comment_list:
            comment_field_value = self.extract_data_field_value(comment_selector)
            if not comment_field_value:
                continue
            tieba_name = comment_selector.xpath("//a[@class='card_title_fname']/text()").get(default="").strip()
            other_info_content = comment_selector.xpath(".//div[@class='post-tail-wrap']").get(default="").strip()
            ip_location, publish_time = self.extract_ip_and_pub_time(other_info_content)
            result.append(
                TiebaComment(
                    comment_id=str(comment_field_value.get("content").get("post_id")),
                    sub_comment_count=comment_field_value.get("content").get("comment_num"),
                    content=utils.extract_text_from_html(comment_field_value.get("content").get("content")),
                    note_url=f"{const.TIEBA_URL}/p/{note_id}",
                    user_link=const.TIEBA_URL + comment_selector.xpath(".//a[@class='p_author_face ']/@href").get(default="").strip(),
                    user_nickname=comment_selector.xpath(".//a[@class='p_author_name j_user_card']/text()").get(default="").strip(),
                    user_avatar=comment_selector.xpath(".//a[@class='p_author_face ']/img/@src").get(default="").strip(),
                    tieba_id=str(comment_field_value.get("content").get("forum_id", "")),
                    tieba_name=tieba_name,
                    tieba_link=f"https://tieba.baidu.com/f?kw={tieba_name}",
                    ip_location=ip_location,
                    publish_time=publish_time,
                    note_id=note_id,
                )
            )
        return result

    def extract_tieba_note_sub_comments(self, page_content: str, parent_comment: TiebaComment) -> list[TiebaComment]:
        selector = Selector(page_content)
        comments: list[TiebaComment] = []
        comment_ele_list = selector.xpath("//li[@class='lzl_single_post j_lzl_s_p first_no_border']")
        comment_ele_list.extend(selector.xpath("//li[@class='lzl_single_post j_lzl_s_p ']"))
        for comment_ele in comment_ele_list:
            comment_value = self.extract_data_field_value(comment_ele)
            if not comment_value:
                continue
            comment_user_a_selector = comment_ele.xpath("./a[@class='j_user_card lzl_p_p']")[0]
            content = utils.extract_text_from_html(comment_ele.xpath(".//span[@class='lzl_content_main']").get(default=""))
            comments.append(
                TiebaComment(
                    comment_id=str(comment_value.get("spid")),
                    content=content,
                    user_link=comment_user_a_selector.xpath("./@href").get(default=""),
                    user_nickname=comment_value.get("showname"),
                    user_avatar=comment_user_a_selector.xpath("./img/@src").get(default=""),
                    publish_time=comment_ele.xpath(".//span[@class='lzl_time']/text()").get(default="").strip(),
                    parent_comment_id=parent_comment.comment_id,
                    note_id=parent_comment.note_id,
                    note_url=parent_comment.note_url,
                    tieba_id=parent_comment.tieba_id,
                    tieba_name=parent_comment.tieba_name,
                    tieba_link=parent_comment.tieba_link,
                )
            )
        return comments

    def extract_creator_info(self, html_content: str) -> TiebaCreator:
        selector = Selector(text=html_content)
        user_link = selector.xpath("//p[@class='space']/a").xpath("./@href").get(default="")
        user_link_params = parse_qs(unquote(user_link.split("?")[-1]))
        user_name = user_link_params.get("un")[0] if user_link_params.get("un") else ""
        user_id = user_link_params.get("id")[0] if user_link_params.get("id") else ""
        userinfo_userdata_selector = selector.xpath("//div[@class='userinfo_userdata']")
        follow_fans_selector = selector.xpath("//span[@class='concern_num']")
        follows, fans = (0, 0)
        if len(follow_fans_selector) == 2:
            follows, fans = self.extract_follow_and_fans(follow_fans_selector)
        user_content = userinfo_userdata_selector.get(default="")
        return TiebaCreator(
            user_id=user_id,
            user_name=user_name,
            nickname=selector.xpath(".//span[@class='userinfo_username ']/text()").get(default="").strip(),
            avatar=selector.xpath(".//div[@class='userinfo_left_head']//img/@src").get(default="").strip(),
            gender=self.extract_gender(user_content),
            ip_location=self.extract_ip(user_content),
            follows=follows,
            fans=fans,
            registration_duration=self.extract_registration_duration(user_content),
        )

    @staticmethod
    def extract_tieba_thread_id_list_from_creator_page(html_content: str) -> list[str]:
        selector = Selector(text=html_content)
        thread_url_list = selector.xpath("//ul[@class='new_list clearfix']//div[@class='thread_name']/a[1]/@href").getall()
        return [thread_url.split("?")[0].split("/")[-1] for thread_url in thread_url_list]

    def extract_ip_and_pub_time(self, html_content: str) -> tuple[str, str]:
        time_match = re.compile(r'<span class="tail-info">(\d{4}-\d{2}-\d{2} \d{2}:\d{2})</span>').search(html_content)
        pub_time = time_match.group(1) if time_match else ""
        return self.extract_ip(html_content), pub_time

    @staticmethod
    def extract_ip(html_content: str) -> str:
        ip_match = re.compile(r"IP属地:(\S+)</span>").search(html_content)
        return ip_match.group(1) if ip_match else ""

    @staticmethod
    def extract_gender(html_content: str) -> str:
        if GENDER_MALE in html_content:
            return "Male"
        if GENDER_FEMALE in html_content:
            return "Female"
        return "Unknown"

    @staticmethod
    def extract_follow_and_fans(selectors: list[Selector]) -> tuple[str, str]:
        pattern = re.compile(r'<span class="concern_num">\(<a[^>]*>(\d+)</a>\)</span>')
        follow_match = pattern.findall(selectors[0].get())
        fans_match = pattern.findall(selectors[1].get())
        return (follow_match[0] if follow_match else 0, fans_match[0] if fans_match else 0)

    @staticmethod
    def extract_registration_duration(html_content: str) -> str:
        match = re.compile(r"<span>吧龄:(\S+)</span>").search(html_content)
        return match.group(1) if match else ""

    @staticmethod
    def extract_data_field_value(selector: Selector) -> dict[str, Any]:
        data_field_value = selector.xpath("./@data-field").get(default="").strip()
        if not data_field_value or data_field_value == "{}":
            return {}
        try:
            return json.loads(html.unescape(data_field_value))
        except Exception:
            return {}
