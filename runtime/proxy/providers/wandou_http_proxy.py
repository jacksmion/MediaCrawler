import os
from typing import Dict, List
from urllib.parse import urlencode

from runtime.http import make_async_client
from tools import utils

from ..base_proxy import IpCache, IpGetError, ProxyProvider
from ..types import IpInfoModel


class WanDouHttpProxy(ProxyProvider):
    def __init__(self, app_key: str, num: int = 100):
        self.proxy_brand_name = "WANDOUHTTP"
        self.api_path = "https://api.wandouapp.com/"
        self.params = {"app_key": app_key, "num": num}
        self.ip_cache = IpCache()

    async def get_proxy(self, num: int) -> List[IpInfoModel]:
        ip_cache_list = self.ip_cache.load_all_ip(proxy_brand_name=self.proxy_brand_name)
        if len(ip_cache_list) >= num:
            return ip_cache_list[:num]

        need_get_count = num - len(ip_cache_list)
        self.params.update({"num": min(need_get_count, 100)})
        ip_infos = []
        async with make_async_client() as client:
            url = self.api_path + "?" + urlencode(self.params)
            utils.logger.info(f"[WanDouHttpProxy.get_proxy] get ip proxy url:{url}")
            response = await client.get(
                url,
                headers={"User-Agent": "MediaCrawler https://github.com/NanmiCoder/MediaCrawler"},
            )
            res_dict: Dict = response.json()
            if res_dict.get("code") == 200:
                data: List[Dict] = res_dict.get("data", [])
                current_ts = utils.get_unix_timestamp()
                for ip_item in data:
                    ip_info_model = IpInfoModel(
                        ip=ip_item.get("ip"),
                        port=ip_item.get("port"),
                        user="",
                        password="",
                        expired_time_ts=utils.get_unix_time_from_time_str(ip_item.get("expire_time")),
                    )
                    ip_key = f"WANDOUHTTP_{ip_info_model.ip}_{ip_info_model.port}"
                    ip_value = ip_info_model.model_dump_json()
                    ip_infos.append(ip_info_model)
                    self.ip_cache.set_ip(ip_key, ip_value, ex=ip_info_model.expired_time_ts - current_ts)
            else:
                error_msg = res_dict.get("msg", "unknown error")
                error_code = res_dict.get("code")
                if error_code == 10001:
                    error_msg = "General error, check msg content for specific error information"
                elif error_code == 10048:
                    error_msg = "No available package"
                raise IpGetError(f"{error_msg} (code: {error_code})")
        return ip_cache_list + ip_infos


def new_wandou_http_proxy() -> WanDouHttpProxy:
    app_key = os.getenv("WANDOU_APP_KEY") or os.getenv("wandou_app_key", "your_wandou_http_app_key")
    return WanDouHttpProxy(app_key=app_key)
