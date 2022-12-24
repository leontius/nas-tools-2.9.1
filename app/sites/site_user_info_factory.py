import importlib
import pkgutil

import requests

import log
from app.helper import ChromeHelper, CHROME_LOCK, SiteHelper
from app.utils import RequestUtils
from app.utils.commons import singleton
from app.utils.exception_utils import ExceptionUtils
from app.utils.types import SiteSchema
from config import Config


@singleton
class SiteUserInfoFactory(object):

    def __init__(self):
        self.__site_schema = {}

        # 从 app.sites.siteuserinfo 下加载所有的站点信息类
        packages = importlib.import_module('app.sites.siteuserinfo').__path__
        for importer, package_name, _ in pkgutil.iter_modules(packages):
            full_package_name = f'app.sites.siteuserinfo.{package_name}'
            if full_package_name.startswith('_'):
                continue
            module = importlib.import_module(full_package_name)
            for name, obj in module.__dict__.items():
                if name.startswith('_'):
                    continue
                if isinstance(obj, type) and hasattr(obj, 'schema'):
                    self.__site_schema[obj.schema] = obj

    def _build_class(self, schema):
        if schema not in self.__site_schema:
            return self.__site_schema.get(SiteSchema.NexusPhp)
        return self.__site_schema[schema]

    def build(self, url, site_name, site_cookie=None, ua=None, emulate=None, proxy=False):
        if not site_cookie:
            return None
        log.debug(f"【Sites】站点 {site_name} url={url} site_cookie={site_cookie} ua={ua}")
        session = requests.Session()
        # 检测环境，有浏览器内核的优先使用仿真签到
        chrome = ChromeHelper()
        if emulate and chrome.get_status():
            with CHROME_LOCK:
                try:
                    chrome.visit(url=url, ua=ua, cookie=site_cookie)
                except Exception as err:
                    print(str(err))
                    log.error("【Sites】%s 无法打开网站" % site_name)
                    return None
                # 循环检测是否过cf
                cloudflare = chrome.pass_cloudflare()
                if not cloudflare:
                    log.error("【Sites】%s 跳转站点失败" % site_name)
                    return None
                # 判断是否已签到
                html_text = chrome.get_html()
        else:
            proxies = Config().get_proxies() if proxy else None
            res = RequestUtils(cookies=site_cookie,
                               session=session,
                               headers=ua,
                               proxies=proxies
                               ).get_res(url=url)
            if res and res.status_code == 200:
                if "charset=utf-8" in res.text or "charset=UTF-8" in res.text:
                    res.encoding = "UTF-8"
                else:
                    res.encoding = res.apparent_encoding
                html_text = res.text
                # 第一次登录反爬
                if html_text.find("title") == -1:
                    i = html_text.find("window.location")
                    if i == -1:
                        return None
                    tmp_url = url + html_text[i:html_text.find(";")] \
                        .replace("\"", "").replace("+", "").replace(" ", "").replace("window.location=", "")
                    res = RequestUtils(cookies=site_cookie,
                                       session=session,
                                       headers=ua,
                                       proxies=proxies
                                       ).get_res(url=tmp_url)
                    if res and res.status_code == 200:
                        if "charset=utf-8" in res.text or "charset=UTF-8" in res.text:
                            res.encoding = "UTF-8"
                        else:
                            res.encoding = res.apparent_encoding
                        html_text = res.text
                        if not html_text:
                            return None
                    else:
                        log.error("【Sites】站点 %s 被反爬限制：%s, 状态码：%s" % (site_name, url, res.status_code))
                        return None

                # 兼容假首页情况，假首页通常没有 <link rel="search" 属性
                if '"search"' not in html_text and '"csrf-token"' not in html_text:
                    res = RequestUtils(cookies=site_cookie,
                                       session=session,
                                       headers=ua,
                                       proxies=proxies
                                       ).get_res(url=url + "/index.php")
                    if res and res.status_code == 200:
                        if "charset=utf-8" in res.text or "charset=UTF-8" in res.text:
                            res.encoding = "UTF-8"
                        else:
                            res.encoding = res.apparent_encoding
                        html_text = res.text
                        if not html_text:
                            return None
            elif not res:
                log.error("【Sites】站点 %s 连接失败：%s" % (site_name, url))
                return None
            else:
                log.error("【Sites】站点 %s 获取流量数据失败，状态码：%s" % (site_name, res.status_code))
                return None

        # 解析站点类型
        site_schema = self._build_class(SiteHelper.schema(html_text))
        return site_schema(site_name, url, site_cookie, html_text, session=session, ua=ua)
