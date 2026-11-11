# -*- coding: utf-8 -*-
"""从网盘天马(Pegasus)拉取 FC 游戏的 ROM + 封面(boxFront/logo)到本地缓存。只读下载，不改网盘。

单款:
  python tianma_fetch.py --game "Ninja Gaiden (USA)" --slug ninja_gaiden_usa \
      --sha1 CA513F841D75EFEB33BB8099FB02BEEB39F6BB9C
批量（网盘 FC-HD 里 zip 与 media 封面齐全的游戏）:
  python tianma_fetch.py --batch 0        # 0=全部；N=前 N 款
  --game  = 网盘 FC-HD 下目录/zip 名；--slug = 本地 covers/<slug> 与 roms_verify/NES/<slug>.nes；
  --sha1  = 期望 ROM 哈希（bk2 Header 的 SHA1），给了就核对，不给则用下载 ROM 实算值落 cover.json。
缓存后 record.py --border auto 会按 ROM sha1 自动套对应封面边框。
"""
import os, sys, json, zipfile, hashlib, urllib.request, io, argparse, re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import netdisk_upload as nu

BASE = "/quark-tuiuw33s/天马6t合集/750A218G"   # 2026-11-10 网盘侧把 750A218G 挪进了 天马6t合集
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "..", "04-游戏资源库", "TAS输入录像库")


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def fetch(a, remote, local):
    os.makedirs(os.path.dirname(local), exist_ok=True)
    if os.path.isfile(local) and os.path.getsize(local) > 0:
        return local
    d = a.api("/api/fs/get", {"path": remote})
    if d.get("code") != 200:
        raise SystemExit("fs/get fail %s: %s" % (remote, d.get("message")))
    x = d.get("data") or {}
    # 夸克直链对裸客户端回 412；走 OpenList 服务端代理（storage web_proxy=True）+ sign。
    import urllib.parse
    url = nu.BASE + "/d" + urllib.parse.quote(remote) + "?sign=" + urllib.parse.quote(x.get("sign") or "")
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=300) as r, open(local, "wb") as f:
        f.write(r.read())
    print("downloaded", remote, "->", local, os.path.getsize(local))
    return local


def list_games(a):
    """FC-HD 下既有 <name>.zip 又有 media/<name>/ 封面的游戏名（排序）。"""
    d = a.api("/api/fs/list", {"path": BASE + "/FC-HD", "page": 1, "per_page": 500})
    zips = {x["name"][:-4] for x in ((d.get("data") or {}).get("content") or [])
            if not x.get("is_dir") and x["name"].lower().endswith(".zip")}
    m = a.api("/api/fs/list", {"path": BASE + "/FC-HD/media", "page": 1, "per_page": 1000})
    media = {x["name"] for x in ((m.get("data") or {}).get("content") or []) if x.get("is_dir")}
    return sorted(zips & media)


def cache_game(a, game, slug=None, want=None):
    """缓存一款：封面+ROM+cover.json(按实算 sha1)。已缓存直接返回。返回 meta dict。"""
    slug = slug or slugify(game)
    cover_dir = os.path.join(ROOT, "covers", slug)
    rom_dir = os.path.join(ROOT, "roms_verify", "NES")
    cj = os.path.join(cover_dir, "cover.json")
    rom_out = os.path.join(rom_dir, slug + ".nes")
    if os.path.isfile(cj) and os.path.isfile(rom_out) and os.path.isfile(os.path.join(cover_dir, "boxFront.png")):
        with open(cj, encoding="utf-8") as f:
            meta = json.load(f)
        if meta.get("rom_sha1"):
            print("cache hit", slug)
            return meta

    rom_zip = fetch(a, BASE + "/FC-HD/" + game + ".zip", os.path.join(cover_dir, "_rom.zip"))
    box = fetch(a, BASE + "/FC-HD/media/" + game + "/boxFront.png",
                os.path.join(cover_dir, "boxFront.png"))
    try:
        logo = fetch(a, BASE + "/FC-HD/media/" + game + "/logo.png",
                     os.path.join(cover_dir, "logo.png"))
    except SystemExit:
        logo = ""   # 个别游戏无 logo，边框只用 boxFront 也成立
    with zipfile.ZipFile(rom_zip) as z:
        nes = [n for n in z.namelist() if n.lower().endswith((".nes", ".unf", ".unif"))]
        if not nes:
            raise SystemExit("no .nes in zip: " + game)
        data = z.read(nes[0])
    sha = hashlib.sha1(data).hexdigest().upper()
    if want:
        if sha != want.upper():
            raise SystemExit("ROM sha1 %s != 期望 %s（%s 版本不符）" % (sha, want, game))
    os.makedirs(rom_dir, exist_ok=True)
    with open(rom_out, "wb") as f:
        f.write(data)
    meta = {"game": game, "slug": slug, "rom_sha1": sha, "boxFront": box, "logo": logo,
            "source": BASE + "/FC-HD"}
    with open(cj, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    try:
        os.remove(rom_zip)   # _transient_：哈希已落 cover.json，ROM 已存 roms_verify
    except OSError:
        pass   # 清理失败不影响已缓存结果（杀软/索引可能短暂占用）
    print("cached", slug, sha)
    return meta


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--game", default=None, help="网盘 FC-HD 下目录/zip 名（单款）")
    ap.add_argument("--slug", default=None, help="本地 covers/<slug> 与 rom 文件名")
    ap.add_argument("--sha1", default=None, help="期望 ROM 哈希；给了就核对")
    ap.add_argument("--batch", type=int, default=None, metavar="N",
                    help="批量缓存网盘 FC-HD 齐全游戏；0=全部，N=前 N 款")
    args = ap.parse_args()
    a = nu.Auth(); a.token()

    if args.batch is not None:
        games = list_games(a)
        if args.batch > 0:
            games = games[:args.batch]
        ok, skip = [], []
        for g in games:
            try:
                ok.append(cache_game(a, g))
            except (SystemExit, Exception) as e:   # 单款失败不中断整批
                skip.append((g, str(e)))
                print("SKIP", g, e)
        print("BATCH done: cached=%d skip=%d / total=%d" % (len(ok), len(skip), len(games)))
        for g, e in skip:
            print("  skip:", g, e)
        return

    game = args.game or "Ninja Gaiden (USA)"
    cache_game(a, game, args.slug, args.sha1)
    print("cover cached ->", os.path.join(ROOT, "covers", args.slug or slugify(game)),
          "(record --border auto 将按 sha1 自动套边框)")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()