// browser_fetch.mjs —— 浏览器层抓取器(2026-10-21 新增,v2 带代理分流)
//
// 为什么要有:curl 拿不到的站点分两种,解法完全不同(实测结论,别混):
//   ① 国外站(psx-place/gtforums/pcsx2forum)—— 本机直连被 RST,不是反爬。
//      解法:chromium 走本机代理(http://127.0.0.1:7890,和 curl 源同一个出口)。
//   ② Cloudflare 挑战页("Just a moment...")—— 换干净 IP(代理)后有机会过,
//      无头过不去就认栽,下周再来,不硬刚。
// 国内站(a9vg/mydigit)直连即可,走代理反而慢。
//
// 用法: node browser_fetch.mjs <sites.json> <out.json>
// sites.json 每项(键名与 Python 侧 browser_watch.py 一致, snake_case):
//   {id,name,url,max_links,wait_ms,proxy?,link_pattern?}
//   proxy: true → 走 HTTPS_PROXY（兜底 127.0.0.1:7891）;link_pattern: 自定义帖子链接正则(默认通用规则)
// out.json: {id:{ok,name,url,title,items:[{title,url,date}],error?}}
import { createRequire } from "node:module";
import { readFileSync, writeFileSync } from "node:fs";

const require = createRequire("f:/rsshub-npm/");   // patchright 装在 RSSHub 那边
const { chromium } = require("patchright");

// 代理口不写死：Clash Verge 11-04 从 7890 换到 7891，所以优先吃环境变量，兜底用新口。
const PROXY = { server: process.env.HTTPS_PROXY || process.env.https_proxy || "http://127.0.0.1:7891" };
const sites = JSON.parse(readFileSync(process.argv[2], "utf8"));
const outPath = process.argv[3];
const result = {};

const browser = await chromium.launch({ headless: true });
const direct = await browser.newContext({
    userAgent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
    locale: "zh-CN",
    viewport: { width: 1366, height: 900 },
});
const proxied = await browser.newContext({
    userAgent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
    locale: "en-US",
    viewport: { width: 1366, height: 900 },
    proxy: PROXY,
});

for (const s of sites) {
    const ctx = s.proxy ? proxied : direct;
    const page = await ctx.newPage();
    try {
        await page.goto(s.url, { waitUntil: "domcontentloaded", timeout: 45000 });
        if (s.wait_ms) await page.waitForTimeout(s.wait_ms);
        const data = await page.evaluate(({ maxLinks, pattern }) => {
            const re = pattern ? new RegExp(pattern, "i")
                : /(threads\/|\/topic\/|viewthread|showthread|\/t\/|\/d\/|discussion|\/node\/|\?tid=|forumdisplay|\/f\/|\/article\/)/i;
            const out = [];
            const seen = new Set();
            for (const a of Array.from(document.querySelectorAll("a[href]"))) {
                const text = (a.textContent || "").replace(/\s+/g, " ").trim();
                const href = a.href;
                if (!text || text.length < 4 || text.length > 160) continue;
                if (seen.has(href)) continue;
                if (/\.(jpg|jpeg|png|gif|webp|css|js|ico|svg|xml)(\?|$)/i.test(href)) continue;
                if (/(login|register|signin|signup|logout|search\?|member|help|privacy|terms|contact|javascript:)/i.test(href)) continue;
                if (!re.test(href)) continue;
                let date = "";
                const box = a.closest("li,tr,div,article,section") || a.parentElement;
                if (box) {
                    const t = box.querySelector("time[datetime],time,.date,.DateTime,.u-dt,.lastPost");
                    if (t) date = (t.getAttribute("datetime") || t.textContent || "").replace(/\s+/g, " ").trim().slice(0, 40);
                }
                seen.add(href);
                out.push({ title: text, url: href, date });
                if (out.length >= maxLinks) break;
            }
            return { title: document.title || "", finalUrl: location.href, items: out };
        }, { maxLinks: s.max_links || 30, pattern: s.link_pattern || "" });
        result[s.id] = { ok: true, name: s.name, url: s.url, ...data };
    } catch (e) {
        result[s.id] = { ok: false, name: s.name, url: s.url, error: String(e).split("\n")[0].slice(0, 160), items: [] };
    } finally {
        await page.close();
    }
}
await browser.close();
writeFileSync(outPath, JSON.stringify(result, null, 1), "utf8");
console.log("fetched " + Object.keys(result).length + " sites -> " + outPath);
