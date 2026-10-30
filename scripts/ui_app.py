from __future__ import annotations

import json
from html import escape
from math import ceil
from pathlib import Path
import sys

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from eryoutoolbox.ui_queries import (  # noqa: E402
    DatabaseReadError,
    distribute_items_to_columns,
    gallery_step_index,
    preview_display_decision,
    query_mod_detail,
    query_mods,
    valid_http_url,
)

DATABASE_PATH = ROOT / "data" / "eryoutoolbox.db"
GAMES_PATH = ROOT / "config" / "games.json"
PAGE_SIZE = 24

st.set_page_config(page_title="二游工具盒 ErYouToolbox", layout="wide")
st.title("二游工具盒 ErYouToolbox")
st.caption("GameBanana 作品库")

st.markdown("""
<style>
.stApp { background: #101820; }
h1, h2, h3 { letter-spacing: -0.02em; }
.stButton > button, .stLinkButton > a {
    border-radius: 8px; font-weight: 600; min-height: 2.35rem;
}
[class*="st-key-mod-card-"] {
    background: #202B36; border-color: #354452; padding: .8rem; margin-bottom: .75rem;
}
.mod-title {
    display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
    overflow: hidden; min-height: 2.8em; line-height: 1.4; font-weight: 700;
}
.mod-meta { color: #b9c5d0; font-size: .92rem; line-height: 1.5; }
.gallery-index { color: #55CABB; font-weight: 700; }
[class*="st-key-gallery-thumb-"] {
    border: 2px solid transparent; border-radius: 8px; padding: 3px;
    transition: border-color .12s ease;
}
.no-preview {
    height: 112px; display: grid; place-items: center; border-radius: 6px;
    background: #18212C; color: #91A0AF; font-size: 2rem;
}
</style>
""", unsafe_allow_html=True)

try:
    games = json.loads(GAMES_PATH.read_text(encoding="utf-8"))["games"]
except (OSError, ValueError, KeyError, TypeError) as exc:
    st.error(f"无法读取游戏配置：{exc}")
    st.stop()

with st.sidebar:
    st.caption("作品库工具")
    st.subheader("浏览与筛选")
    game_labels = ["全部游戏", *(game["name"] for game in games)]
    selected_game = st.selectbox("游戏", game_labels)
    search = st.text_input("搜索 MOD 标题、作者或 MOD ID")
    sort_label = st.selectbox("排序", ["首次发现时间", "发布时间", "来源更新时间"])
    sort_key = {"首次发现时间": "first_seen", "发布时间": "created", "来源更新时间": "updated"}[sort_label]
    show_unrated = st.toggle("显示未评级作品预览图", value=False,
                             help="仅对当前页面会话生效，不会更改数据库分级。")

selected_game_id = None
if selected_game != "全部游戏":
    selected_game_id = next(game["game_id"] for game in games if game["name"] == selected_game)
filter_key = (selected_game_id, search, sort_key)
if st.session_state.get("_filter_key") != filter_key:
    st.session_state["_filter_key"] = filter_key
    st.session_state["page"] = 0
page_index = st.session_state.get("page", 0)

try:
    result = query_mods(DATABASE_PATH, game_id=selected_game_id, search=search,
                        sort=sort_key, limit=PAGE_SIZE, offset=page_index * PAGE_SIZE)
except DatabaseReadError as exc:
    st.error(f"数据库只读访问失败：{exc}")
    st.info("请确认数据库存在且可读取。界面不会自动创建或初始化数据库。")
    st.stop()

total_count = result["total_count"]
page_count = max(1, ceil(total_count / PAGE_SIZE))
if page_index >= page_count:
    st.session_state["page"] = page_count - 1
    st.rerun()

st.caption(f"匹配作品：{total_count} 条 | 第 {page_index + 1} / {page_count} 页")
items = result["items"]
try:
    test_items = query_mods(
        DATABASE_PATH, game_id=selected_game_id, search=search, sort=sort_key,
        limit=4, offset=0, require_preview=True,
    )["items"]
except DatabaseReadError as exc:
    test_items = []
    st.warning(f"测试作品查询失败：{exc}")

def _move_gallery(index_key: str, image_count: int, step: int) -> None:
    current = st.session_state.get(index_key, 0)
    target = gallery_step_index(current, image_count, step)
    st.session_state[index_key] = target


@st.dialog("MOD 详情", width="large")
def show_mod_detail(source: str, item_type: str, item_id: int, allow_unrated: bool) -> None:
    try:
        detail = query_mod_detail(DATABASE_PATH, source=source,
                                  item_type=item_type, item_id=item_id)
    except DatabaseReadError as exc:
        st.error(f"读取作品详情失败：{exc}")
        return
    if detail is None:
        st.error("作品详情暂时无法读取。")
        return

    index_key = f"gallery_index_{source}_{item_type}_{item_id}"
    gallery_images = detail.get("preview_images", [])
    preview_state, _ = preview_display_decision(detail, show_unrated=allow_unrated)
    left, right = st.columns([3, 2], gap="large")
    with left:
        if preview_state == "DISPLAY" and gallery_images:
            index = min(max(st.session_state.get(index_key, 0), 0), len(gallery_images) - 1)
            st.session_state[index_key] = index
            previous_col, count_col, next_col = st.columns([1, 2, 1], vertical_alignment="center")
            with previous_col:
                st.button("‹ 上一张", key=f"gallery_prev_{item_id}", disabled=index <= 0,
                          on_click=_move_gallery,
                          args=(index_key, len(gallery_images), -1),
                          use_container_width=True)
            with count_col:
                st.markdown(f'<div class="gallery-index">{index + 1} / {len(gallery_images)}</div>',
                            unsafe_allow_html=True)
            with next_col:
                st.button("下一张 ›", key=f"gallery_next_{item_id}",
                          disabled=index + 1 >= len(gallery_images), on_click=_move_gallery,
                          args=(index_key, len(gallery_images), 1),
                          use_container_width=True)
            try:
                st.image(gallery_images[index]["image_url"], use_container_width=True)
            except Exception:
                st.warning("这张图片暂时无法加载。")

            st.caption("图片缩略图")
            thumb_start = min(max(index - 2, 0), max(0, len(gallery_images) - 6))
            visible_indices = range(thumb_start, min(thumb_start + 6, len(gallery_images)))
            thumbnail_columns = st.columns(len(visible_indices), gap="small")
            for image_index, column in zip(visible_indices, thumbnail_columns):
                with column:
                    with st.container(key=f"gallery-thumb-{item_id}-{image_index}"):
                        try:
                            st.image(gallery_images[image_index]["switch_url"], width=88)
                        except Exception:
                            st.caption("不可用")
            st.markdown(
                f"<style>.st-key-gallery-thumb-{item_id}-{index} "
                "{border-color:#55CABB;box-shadow:0 0 0 1px #55CABB;}</style>",
                unsafe_allow_html=True,
            )
        else:
            messages = {
                "NO_IMAGE": "暂无已保存的预览图。",
                "UNKNOWN_HIDDEN": "作品尚未评级，预览图默认隐藏。",
                "NSFW_HIDDEN": "成人内容预览图已隐藏。",
                "RATING_HIDDEN": "当前内容分级不允许展示预览图。",
                "INVALID_URL": "没有可用的图片地址。",
                "DISPLAY_ERROR": "预览图暂时无法显示。",
            }
            st.info(messages.get(preview_state, "暂无可显示的预览图。"))

    with right:
        st.header(detail.get("title") or "暂无数据")
        st.caption(f"MOD ID · {detail['item_id']}  |  {detail.get('game_name') or '暂无数据'}")
        author_name = detail.get("author_name") or "暂无数据"
        if valid_http_url(detail.get("author_url")):
            st.link_button(f"作者 · {author_name}", detail["author_url"])
        else:
            st.write(f"作者 · {author_name}")
        if detail.get("author_id") is not None:
            st.caption(f"作者 ID · {detail['author_id']}")
        original_url = detail.get("original_url")
        if valid_http_url(original_url):
            st.link_button("打开 GameBanana 原帖", original_url, use_container_width=True)
        st.divider()
        categories = " / ".join(part for part in (detail.get("category"), detail.get("subcategory")) if part)
        tags = detail.get("tags") or []
        st.markdown(f"**分类**　{categories or '暂无数据'}")
        st.markdown(f"**标签**　{', '.join(tags) if tags else '暂无数据'}")
        st.markdown(f"**版本**　{detail.get('version') or '暂无数据'}")
        st.markdown(f"**发布时间**　{detail.get('created_at') or '暂无数据'}")
        st.markdown(f"**来源更新时间**　{detail.get('updated_at') or '暂无数据'}")
        st.markdown(f"**内容分级**　{detail.get('content_rating_status') or 'UNKNOWN'}")
        with st.expander("作品简介", expanded=False):
            if detail.get("description"):
                st.text(detail["description"])
            else:
                st.caption("暂无数据")


st.subheader("已收录图片 · 测试作品")
st.caption("仅用于界面验证，不代表最新推荐作品。")
if not test_items:
    st.info("当前筛选下暂无已保存预览图的作品。")
test_columns = st.columns(4, gap="small")
for test_item, column in zip(test_items, test_columns):
    with column:
        test_mod_id = test_item["item_id"]
        with st.container(border=True, key=f"test-mod-card-{test_item['source']}-{test_item['item_type']}-{test_mod_id}"):
            decision, previews = preview_display_decision(test_item, show_unrated=show_unrated)
            if decision == "DISPLAY" and previews:
                try:
                    st.image(previews[0], use_container_width=True)
                except Exception:
                    st.markdown('<div class="no-preview">图片加载失败</div>', unsafe_allow_html=True)
            else:
                placeholder = "作品尚未评级，预览已隐藏" if decision == "UNKNOWN_HIDDEN" else "暂无可显示图片"
                st.markdown(f'<div class="no-preview">{escape(placeholder)}</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="mod-title">{escape(test_item.get("title") or "（无标题）")}</div>',
                        unsafe_allow_html=True)
            st.markdown(f'<div class="mod-meta">作者 · {escape(test_item.get("author_name") or "暂无数据")}</div>',
                        unsafe_allow_html=True)
            if st.button("查看详情", key=f"test-detail_{test_mod_id}", use_container_width=True):
                test_state_key = f"gallery_index_{test_item['source']}_{test_item['item_type']}_{test_mod_id}"
                st.session_state[test_state_key] = 0
                show_mod_detail(test_item["source"], test_item["item_type"], test_mod_id, show_unrated)


columns = st.columns(4, gap="small")
for column, column_items in zip(columns, distribute_items_to_columns(items, 4)):
    with column:
        for item in column_items:
            with st.container(border=True, key=f"mod-card-{item['source']}-{item['item_type']}-{item['item_id']}"):
                title = item.get("title") or "（无标题）"
                st.markdown(f'<div class="mod-title">{escape(title)}</div>', unsafe_allow_html=True)
                preview_state, previews = preview_display_decision(item, show_unrated=show_unrated)
                if preview_state == "DISPLAY":
                    try:
                        st.image(previews[0], use_container_width=True)
                    except Exception:
                        preview_state = "DISPLAY_ERROR"
                if preview_state != "DISPLAY":
                    st.markdown('<div class="no-preview">⌕</div>', unsafe_allow_html=True)
                    messages = {
                        "NO_IMAGE": "暂无预览图",
                        "UNKNOWN_HIDDEN": "◌ 未评级 · 预览已隐藏",
                        "NSFW_HIDDEN": "◌ 成人内容 · 预览已隐藏",
                        "RATING_HIDDEN": "◌ 当前分级 · 预览已隐藏",
                        "INVALID_URL": "◌ 预览地址无效",
                        "DISPLAY_ERROR": "◌ 图片加载失败",
                    }
                    st.caption(messages.get(preview_state, "◌ 暂无可用预览"))
                author_game = f"{item.get('author_name') or '未知作者'} · {item.get('game_name') or '未知游戏'}"
                st.markdown(f'<div class="mod-meta">{escape(author_game)}</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="mod-meta">更新 · {escape(str(item.get("updated_at") or "暂无数据"))}</div>',
                            unsafe_allow_html=True)
                if item.get("workflow_status") and item["workflow_status"] != "none":
                    st.caption(f"管理状态：{item['workflow_status']}")
                if item.get("is_favorite"):
                    st.caption("已收藏")
                if item.get("is_read"):
                    st.caption("已读")
                if item.get("is_ignored"):
                    st.caption("已忽略")
                original_url = item.get("original_url")
                action_cols = st.columns(2, gap="small")
                with action_cols[0]:
                    if valid_http_url(original_url):
                        st.link_button("原帖 ↗", original_url, use_container_width=True)
                    else:
                        st.caption("原帖暂无")
                with action_cols[1]:
                    open_detail = st.button("查看详情", key=f"detail_{item['source']}_{item['item_type']}_{item['item_id']}",
                                             use_container_width=True)
                if open_detail:
                    gallery_state_key = f"gallery_index_{item['source']}_{item['item_type']}_{item['item_id']}"
                    st.session_state[gallery_state_key] = 0
                    show_mod_detail(item["source"], item["item_type"], item["item_id"], show_unrated)

previous_col, page_col, next_col = st.columns([1, 2, 1])
with previous_col:
    if st.button("上一页", disabled=page_index <= 0, use_container_width=True):
        st.session_state["page"] = max(0, page_index - 1)
        st.rerun()
with page_col:
    st.caption(f"第 {page_index + 1} 页，共 {page_count} 页")
with next_col:
    if st.button("下一页", disabled=page_index + 1 >= page_count, use_container_width=True):
        st.session_state["page"] = page_index + 1
        st.rerun()
