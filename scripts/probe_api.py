"""Small, sequential feasibility probe for public GameBanana APIs."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx


ROOT = Path(__file__).resolve().parents[1]
GAMES_FILE = ROOT / "config" / "games.json"
LOG_DIR = ROOT / "logs"
TIMEOUT = httpx.Timeout(15.0, connect=8.0)
DELAY_SECONDS = 1.0
MAX_RETRIES = 1
HEADERS = {"User-Agent": "ErYouToolbox/0.1 public-api-feasibility-probe"}


class ProbeError(Exception):
    pass


def request(client: httpx.Client, url: str, params: dict[str, Any] | None = None) -> Any:
    """Make one request, with at most one retry for non-429 transient failures."""
    attempt = 0
    while True:
        try:
            response = client.get(url, params=params)
            print(f"  请求: {response.request.url}")
            print(f"  HTTP 状态: {response.status_code}")
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                if retry_after:
                    try:
                        wait = max(0.0, min(float(retry_after), 120.0))
                    except ValueError:
                        wait = 0.0
                    if wait:
                        print(f"  收到 429，遵守 Retry-After 等待 {wait:g} 秒后停止本次探测。")
                        time.sleep(wait)
                raise ProbeError("HTTP 429：已停止后续请求，避免继续触发限流。")
            response.raise_for_status()
            try:
                return response.json()
            except (ValueError, json.JSONDecodeError) as exc:
                raise ProbeError(f"响应不是有效 JSON：{exc}") from exc
        except ProbeError:
            raise
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if attempt < MAX_RETRIES and status >= 500:
                attempt += 1
                print("  服务端临时错误，等待后重试一次。")
                time.sleep(2.0)
                continue
            raise ProbeError(f"HTTP 错误：{status}") from exc
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            if attempt < MAX_RETRIES:
                attempt += 1
                print(f"  临时网络错误，等待后重试一次：{exc}")
                time.sleep(2.0)
                continue
            raise ProbeError(f"网络请求失败：{type(exc).__name__}: {exc}") from exc


def keys_of(value: Any) -> list[str]:
    if isinstance(value, dict):
        return list(value.keys())[:15]
    if isinstance(value, list) and value and isinstance(value[0], dict):
        return list(value[0].keys())[:15]
    return []


def sample_ids(value: Any, limit: int = 3) -> list[str]:
    """Extract IDs from Core/List/New [itemtype, itemid] rows or keyed objects."""
    found: list[str] = []
    malformed_rows = 0

    if isinstance(value, list):
        for row in value:
            if isinstance(row, list):
                if len(row) != 2:
                    malformed_rows += 1
                    continue
                item_type, item_id = row
                if not isinstance(item_type, str) or not isinstance(item_id, int) or isinstance(item_id, bool):
                    malformed_rows += 1
                    continue
                if item_type.lower() == "mod" and item_id > 0:
                    found.append(str(item_id))
                    if len(found) >= limit:
                        break

    def walk(node: Any) -> None:
        if len(found) >= limit:
            return
        if isinstance(node, dict):
            for key, item in node.items():
                if key.lower() in {"id", "itemid", "modid"} and isinstance(item, (int, str)):
                    text = str(item)
                    if text.isdigit() and text not in found:
                        found.append(text)
                walk(item)
        elif isinstance(node, list):
            for item in node:
                walk(item)
                if len(found) >= limit:
                    break

    if isinstance(value, dict):
        walk(value)
    if not found and malformed_rows:
        print(f"  ID 解析诊断: {malformed_rows} 条数组记录不符合 [string itemtype, integer itemid] 格式。")
    elif isinstance(value, list) and value and not found:
        if all(isinstance(row, list) and len(row) == 2 for row in value):
            print("  ID 解析诊断: 返回记录格式有效，但没有 MOD 类型的正整数 ID。")
        else:
            print("  ID 解析诊断: 顶层列表结构与预期的 [itemtype, itemid] 记录不一致。")
    elif not isinstance(value, (list, dict)):
        print(f"  ID 解析诊断: 不支持的响应类型 {type(value).__name__}；预期 list 或 dict。")
    return found


def summarize(label: str, value: Any) -> None:
    print(f"  JSON 类型: {type(value).__name__}")
    if isinstance(value, list):
        print(f"  顶层记录数: {len(value)}")
    elif isinstance(value, dict):
        print(f"  顶层键: {list(value.keys())[:15]}")
    print(f"  关键字段名: {keys_of(value)}")
    print(f"  样本作品 ID: {sample_ids(value)}")


def list_new(client: httpx.Client, game_id: int, page: int = 1,
             include_updated: int = 0) -> Any:
    # Explicitly requested Core/List/New parameters; one item type and bounded page.
    return request(client, "https://api.gamebanana.com/Core/List/New", {
        "gameid": game_id,
        "itemtype": "Mod",
        "page": page,
        # max_age is measured in seconds: 86400 is 24 hours; 30 days is 2592000.
        "max_age": 86400,
        "include_updated": include_updated,
    })


def main() -> int:
    try:
        games = json.loads(GAMES_FILE.read_text(encoding="utf-8"))["games"]
    except Exception as exc:
        print(f"无法读取游戏配置：{exc}")
        return 1

    LOG_DIR.mkdir(exist_ok=True)
    outcomes: list[dict[str, Any]] = []
    print("GameBanana 公开 API 可行性探测（顺序请求、无文件/图片下载）")
    with httpx.Client(timeout=TIMEOUT, headers=HEADERS, follow_redirects=True) as client:
        # Six first pages + Genshin page 2 + include_updated=1 = 8 list calls.
        for game in games:
            name, game_id = game["name"], game["game_id"]
            print(f"\n游戏名称: {name}\nGame ID: {game_id}")
            try:
                value = list_new(client, game_id)
                summarize("list", value)
                count = len(value) if isinstance(value, list) else 0
                outcomes.append({"name": name, "game_id": game_id, "status": "成功", "count": count})
            except ProbeError as exc:
                print(f"  失败原因: {exc}")
                outcomes.append({"name": name, "game_id": game_id, "status": "失败", "error": str(exc)})
                if "429" in str(exc):
                    break
            time.sleep(DELAY_SECONDS)

        genshin = next((g for g in games if g["game_id"] == 8552), None)
        if genshin and not any("429" in str(o.get("error", "")) for o in outcomes):
            for label, page, updated in (("原神第二页", 2, 0), ("原神 include_updated=1", 1, 1)):
                print(f"\n{label}（Game ID: 8552）")
                try:
                    value = list_new(client, 8552, page, updated)
                    summarize("list", value)
                except ProbeError as exc:
                    print(f"  失败原因: {exc}")
                    if "429" in str(exc):
                        break
                time.sleep(DELAY_SECONDS)

        print("\nCore/Item/Data：")
        print("  未执行：官方文档在当前环境不可访问；需先确认 Mod 类型允许字段并从真实列表取得 Mod ID，不能猜字段名。")
        print("\napiv11/Mod/Index：")
        print("  未执行：官方文档在当前环境不可访问，游戏过滤参数尚未确认；不提交未经验证的过滤参数。")

    print("\nAPI 可行性简报")
    success = [o for o in outcomes if o["status"] == "成功"]
    print(f"- 实际成功接口：Core/List/New 成功 {len(success)}/{len(games)} 个游戏首屏请求；具体结果见上方。")
    print("- 请求参数：gameid/itemtype/page/max_age/include_updated 按要求提交；只有成功响应才视为参数得到运行验证。")
    print("- JSON 结构：逐项输出类型、顶层键或记录数、关键字段名与最多 3 个样本 ID。")
    print("- 更新识别候选：Core/List/New 的排序/更新时间相关返回字段如有出现会在字段名中显示；当前未预设具体字段。")
    print("- 尚未验证：Core/Item/Data 字段目录与详情、apiv11 游戏过滤和列表结构、更新时间字段语义及内容分级。")
    try:
        (LOG_DIR / "probe_summary.json").write_text(
            json.dumps(outcomes, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"摘要日志：{LOG_DIR / 'probe_summary.json'}")
    except OSError as exc:
        print(f"摘要日志写入失败（探测结果仍已显示）：{exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
