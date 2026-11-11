# -*- coding: utf-8 -*-
"""TASVideos 出版物镜像落库工具。

只抓输入录像(movie)与元数据，不抓 ROM、不抓视频成品。
数据来源 tasvideos.org 公开列表页/版本页，限速抓取，断点续传。

用法:
  python tasvideos_mirror.py index   [--platform NES] [--force]
  python tasvideos_mirror.py movies  [--platform NES] [--limit N]
  python tasvideos_mirror.py versions
  python tasvideos_mirror.py all     [--platform NES]
  python tasvideos_mirror.py status

落库结构 (04-游戏资源库/TAS输入录像库/):
  publications.json        全部出版物索引(含本地 movie 路径字段)
  movies/<平台>/<id>.<ext> 输入录像文件
  versions/<gid>_<vid>.json 游戏版本 ROM hash 要求
  _cache/<平台>_<页>.html  列表页原始缓存(可删)
"""
import argparse
import html as html_mod
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error

BASE = "https://tasvideos.org"
LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "04-游戏资源库", "TAS输入录像库")
INDEX = os.path.join(LIB, "publications.json")
UA = {"User-Agent": "TAS-Archive-Personal-Mirror/1.0 (respectful rate-limited research)"}
DELAY = 0.6

PLATFORMS = ['32X', '3DO', '3DS', 'A2600', 'A7800', 'Amiga', 'AppleII', 'Arcade',
             'BSX', 'C64', 'CDi', 'ChannelF', 'Coleco', 'DOS', 'DS', 'DSi', 'FDS',
             'Flash', 'GB', 'GBA', 'GBC', 'GC', 'GG', 'Genesis', 'INTV', 'J2ME',
             'Jaguar', 'JaguarCD', 'Lynx', 'MSX', 'MacOS', 'N64', 'N64DD', 'NES',
             'NGP', 'O2', 'PC', 'PC98', 'PCE', 'PCECD', 'PCFX', 'PICO8', 'PSX',
             'SG1000', 'SGB', 'SGX', 'SMS', 'SNES', 'SVI3x8', 'Saturn', 'SegaCD',
             'TI83', 'TIC80', 'Uzebox', 'VBoy', 'VEC', 'WSWAN', 'Wii', 'X1', 'ZXS']


def fetch(url, binary=False, retries=4):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
            time.sleep(DELAY)
            return data if binary else data.decode("utf-8", "replace")
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
            code = getattr(e, "code", None)
            if code == 404:
                return None
            wait = 3 * (attempt + 1)
            print(f"  retry {attempt+1}/{retries} {url} ({e}) wait {wait}s", flush=True)
            time.sleep(wait)
    raise RuntimeError(f"fetch failed: {url}")


def strip_tags(s):
    return html_mod.unescape(re.sub(r"<[^>]+>", "", s)).strip()


def load_index():
    if os.path.isfile(INDEX):
        with open(INDEX, encoding="utf-8") as f:
            return json.load(f)
    return {"source": BASE, "fetched_at": None, "platforms_done": [], "publications": {}}


def save_index(idx):
    idx["fetched_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    idx["platforms_done"] = sorted(set(idx["platforms_done"]))
    os.makedirs(LIB, exist_ok=True)
    tmp = INDEX + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, indent=1)
    os.replace(tmp, INDEX)


CARD_SPLIT = re.compile(r'<div class="border border-publication card">')


def parse_cards(page_html, platform):
    out = []
    for chunk in CARD_SPLIT.split(page_html)[1:]:
        m = re.search(r'href="/(\d+)M"', chunk)
        if not m:
            continue
        pid = m.group(1)
        rec = {"id": pid, "url": f"{BASE}/{pid}M", "platform": platform}

        m = re.search(r'<span class="text-body-emphasis">\s*(.*?)\s*</span>', chunk, re.S)
        if m:
            head = m.group(1)
            rec["title"] = strip_tags(head)
            am = re.search(r'by\s*(.*?)\s*in\s*([\d:.]+)\s*$', strip_tags(head))
            if am:
                rec["authors"] = am.group(1)
                rec["time"] = am.group(2)

        m = re.search(r'title="([^"]+)"[^>]*>on ([\d/]+)</span>', chunk)
        if m:
            rec["published_utc"] = html_mod.unescape(m.group(1))
            rec["published_date"] = m.group(2)

        m = re.search(r'href="/(\d+)G"[^>]*>([^<]+)</a>', chunk)
        if m:
            rec["game_id"] = m.group(1)
            rec["game"] = html_mod.unescape(m.group(2))

        gm = re.search(r'Genres:<br\s*/>(.*?)</span>', chunk, re.S)
        rec["genres"] = [html_mod.unescape(g) for g in re.findall(r'>([^<]+)</a>', gm.group(1))] if gm else []
        tm = re.search(r'Tags:<br\s*/>(.*?)</span>', chunk, re.S)
        rec["tags"] = [html_mod.unescape(t) for t in re.findall(r'>([^<]+)</a>', tm.group(1))] if tm else []

        m = re.search(r'href="(/Games/(\d+)/Versions/View/(\d+))[^"]*">\s*(.*?)\s*</a>', chunk, re.S)
        if m:
            rec["version_url"] = BASE + m.group(1)
            rec["version_id"] = f'{m.group(2)}_{m.group(3)}'
            rec["version_name"] = strip_tags(m.group(4))

        rec["video_links"] = re.findall(r'href="(https://archive\.org/download/[^"]+)"', chunk)

        m = re.search(r'Emulator Replay:.*?<span class="ms-2">([^<]+)</span>', chunk, re.S)
        if m:
            rec["emulator"] = html_mod.unescape(m.group(1)).strip()
        m = re.search(r'href="(/\d+M\?handler=Download)">.*?Download \(([^)]+)\)', chunk, re.S)
        if m:
            rec["movie_url"] = BASE + html_mod.unescape(m.group(1))
            rec["movie_ext"] = m.group(2).strip().lstrip(".")

        rec["console_verified"] = 'title="Console-verified"' in chunk
        m = re.search(r'id="overallRating-\d+">([\d.]+)', chunk)
        if m:
            rec["rating"] = float(m.group(1))
        out.append(rec)
    return out


def cmd_index(args):
    idx = load_index()
    plats = [args.platform] if args.platform else PLATFORMS
    cache_dir = os.path.join(LIB, "_cache")
    os.makedirs(cache_dir, exist_ok=True)
    for plat in plats:
        if plat in idx["platforms_done"] and not args.force:
            print(f"[skip] {plat} already indexed")
            continue
        print(f"[index] {plat}", flush=True)
        page = 0
        count = 0
        while True:
            cache = os.path.join(cache_dir, f"{plat}_{page}.html")
            if os.path.isfile(cache) and not args.force:
                text = open(cache, encoding="utf-8").read()
            else:
                url = f"{BASE}/Movies-{plat}?CurrentPage={page}&PageSize=100"
                text = fetch(url)
                if text is None:
                    break
                with open(cache, "w", encoding="utf-8") as f:
                    f.write(text)
            recs = parse_cards(text, plat)
            if not recs:
                break
            for r in recs:
                idx["publications"][r["id"]] = r
            count += len(recs)
            print(f"  page {page}: {len(recs)} (total {count})", flush=True)
            if f'CurrentPage={page+1}&' not in text.replace("&amp;", "&"):
                break
            page += 1
        idx["platforms_done"].append(plat)
        save_index(idx)
    print(f"index done: {len(idx['publications'])} publications")


def cmd_movies(args):
    idx = load_index()
    pubs = sorted(idx["publications"].values(), key=lambda r: int(r["id"]))
    if args.platform:
        pubs = [r for r in pubs if r["platform"] == args.platform]
    done = skipped = failed = 0
    for r in pubs:
        if "movie_url" not in r:
            continue
        ext = r.get("movie_ext", "bin")
        rel = os.path.join("movies", r["platform"], f'{r["id"]}.{ext}')
        path = os.path.join(LIB, rel)
        if os.path.isfile(path) and os.path.getsize(path) > 0:
            r["local_movie"] = rel.replace("\\", "/")
            skipped += 1
            continue
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            data = fetch(r["movie_url"], binary=True)
        except RuntimeError as e:
            print(f"[fail] {r['id']}: {e}", flush=True)
            failed += 1
            continue
        if data is None:
            print(f"[404] {r['id']} movie gone", flush=True)
            failed += 1
            continue
        with open(path, "wb") as f:
            f.write(data)
        r["local_movie"] = rel.replace("\\", "/")
        done += 1
        if done % 50 == 0:
            save_index(idx)
            print(f"  downloaded {done} (skip {skipped}, fail {failed})", flush=True)
        if args.limit and done >= args.limit:
            break
    save_index(idx)
    print(f"movies done: new {done}, existing {skipped}, failed {failed}")


def parse_version(text):
    info = {}
    for key, val in re.findall(
            r'<div class="info-entry">\s*<label[^>]*>([^<]+)</label>\s*<label>(.*?)</label>',
            text, re.S):
        info[key.strip()] = strip_tags(val)
    return info


def cmd_versions(args):
    idx = load_index()
    wanted = {}
    for r in idx["publications"].values():
        if "version_url" in r:
            wanted[r["version_id"]] = r["version_url"]
    vdir = os.path.join(LIB, "versions")
    os.makedirs(vdir, exist_ok=True)
    done = skipped = failed = 0
    for vid, url in sorted(wanted.items()):
        path = os.path.join(vdir, vid + ".json")
        if os.path.isfile(path):
            skipped += 1
            continue
        text = fetch(url)
        if text is None:
            failed += 1
            continue
        info = parse_version(text)
        info["url"] = url
        with open(path, "w", encoding="utf-8") as f:
            json.dump(info, f, ensure_ascii=False, indent=1)
        done += 1
        if done % 50 == 0:
            print(f"  versions {done} (skip {skipped}, fail {failed})", flush=True)
    # 把 hash 回填进索引
    hashes = {}
    for fn in os.listdir(vdir):
        if fn.endswith(".json"):
            with open(os.path.join(vdir, fn), encoding="utf-8") as f:
                hashes[fn[:-5]] = json.load(f)
    for r in idx["publications"].values():
        v = hashes.get(r.get("version_id"))
        if v:
            r["rom_sha1"] = v.get("SHA-1", "")
            r["rom_md5"] = v.get("MD5", "")
    save_index(idx)
    print(f"versions done: new {done}, existing {skipped}, failed {failed}, unique {len(wanted)}")


def cmd_status(args):
    idx = load_index()
    pubs = list(idx["publications"].values())
    have_movie = sum(1 for r in pubs if r.get("local_movie") and
                     os.path.isfile(os.path.join(LIB, r["local_movie"])))
    have_hash = sum(1 for r in pubs if r.get("rom_sha1"))
    by_plat = {}
    for r in pubs:
        by_plat.setdefault(r["platform"], [0, 0])
        by_plat[r["platform"]][0] += 1
        if r.get("local_movie"):
            by_plat[r["platform"]][1] += 1
    print(f"publications: {len(pubs)} | movie files: {have_movie} | with sha1: {have_hash}")
    print(f"platforms indexed: {len(idx['platforms_done'])}/{len(PLATFORMS)}")
    for p in sorted(by_plat):
        t, h = by_plat[p]
        print(f"  {p:10s} {h:5d}/{t}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cmd", choices=["index", "movies", "versions", "all", "status"])
    ap.add_argument("--platform")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    if args.cmd in ("index", "all"):
        cmd_index(args)
    if args.cmd in ("movies", "all"):
        cmd_movies(args)
    if args.cmd in ("versions", "all"):
        cmd_versions(args)
    if args.cmd == "status":
        cmd_status(args)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()