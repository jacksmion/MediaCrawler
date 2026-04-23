import os
from typing import Dict, List
from urllib.parse import urlencode

from runtime.http import make_async_client
from tools import utils

from runtime.proxy import IpCache, IpGetError, ProxyProvider
from runtime.proxy.types import IpInfoModel


class JiSuHttpProxy(ProxyProvider):
    def __init__(self, key: str, crypto: str, time_validity_period: int):
        self.proxy_brand_name = "JISUHTTP"
        self.api_path = "https://api.jisuhttp.com"
        self.params = {
            "key": key,
            "crypto": crypto,
            "time": time_validity_period,
            "type": "json",
            "port": "2",
            "pw": "1",
            "se": "1",
        }
        self.ip_cache = IpCache()

    async def get_proxy(self, num: int) -> List[IpInfoModel]:
        ip_cache_list = self.ip_cache.load_all_ip(proxy_brand_name=self.proxy_brand_name)
        if len(ip_cache_list) >= num:
            return ip_cache_list[:num]

        need_get_count = num - len(ip_cache_list)
        self.params.update({"num": need_get_count})
        ip_infos = []
        async with make_async_client() as client:
            url = self.api_path + "/fetchips?" + urlencode(self.params)
            utils.logger.info(f"[JiSuHttpProxy.get_proxy] get ip proxy url:{url}")
            response = await client.get(
                url,
                headers={"User-Agent": "MediaCrawler https://github.com/NanmiCoder/MediaCrawler"},
            )
            res_dict: Dict = response.json()
            if res_dict.get("code") == 0:
                data: List[Dict] = res_dict.get("data")
                current_ts = utils.get_unix_timestamp()
                for ip_item in data:
                    ip_info_model = IpInfoModel(
                        ip=ip_item.get("ip"),
                        port=ip_item.get("port"),
                        user=ip_item.get("user"),
                        password=ip_item.get("pass"),
                        expired_time_ts=utils.get_unix_time_from_time_str(ip_item.get("expire")),
                    )
                    ip_key = f"JISUHTTP_{ip_info_model.ip}_{ip_info_model.port}_{ip_info_model.user}_{ip_info_model.password}"
                    ip_value = ip_info_model.json()
                    ip_infos.append(ip_info_model)
                    self.ip_cache.set_ip(ip_key, ip_value, ex=ip_info_model.expired_time_ts - current_ts)
            else:
                raise IpGetError(res_dict.get("msg", "unkown err"))
        return ip_cache_list + ip_infos


def new_jisu_http_proxy() -> JiSuHttpProxy:
    return JiSuHttpProxy(
        key=os.getenv("jisu_key", ""),
        crypto=os.getenv("jisu_crypto", ""),
        time_validity_period=30,
    )
