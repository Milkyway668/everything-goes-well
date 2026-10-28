# -*- coding: utf-8 -*-
"""确认并写入看板。

单独做成 Python 而不是写在 bat 里，是因为 Windows 的命令行按 GBK 读 bat，
bat 里写中文会乱码、连 if 判断都会被拆坏。这里所有中文都由 Python 输出。
"""
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
os.chdir(BASE)
import sync  # noqa: E402


def pause(msg="\n按回车键关闭窗口…"):
    try:
        input(msg)
    except (EOFError, KeyboardInterrupt):
        pass


def status_name(s):
    return sync.STATUS_NAME.get(s, s)


def main():
    if not os.path.exists(sync.PENDING_MD):
        print("\n还没有待确认清单。")
        print("请先双击「1_扫描邮箱.bat」，扫完再回来点这个。")
        pause()
        return

    p = sync.load_json(sync.PENDING, None) or {}
    new = p.get("new_records", [])
    upd = p.get("updates", [])
    unm = p.get("unmatched", [])

    print("\n" + "=" * 56)
    print(f"待确认清单（{p.get('generated_at', '')}）")
    print("=" * 56)
    print(f"  新投递      {len(new)} 条   ← 会新建记录")
    print(f"  进度更新    {len(upd)} 条   ← 会追加到已有记录")
    print(f"  未匹配      {len(unm)} 条   ← 不会写入，只供参考")
    print("-" * 56)
    for r in new:
        print(f"  [新] {r['company']} / {r['position']}  ({r['_source']['date']})")
    for u in upd:
        print(f"  [更] {u.get('target_company', '')} → {status_name(u['status'])}  ({u['date']})")
    print("=" * 56)

    if not new and not upd:
        print("\n这次没有需要写入的内容。")
        print("（清单里只有已存在或未匹配的条目，看板不用改）")
        try:
            os.startfile(sync.PENDING_MD)
        except Exception:
            pass
        pause()
        return

    try:
        os.startfile(sync.PENDING_MD)
        print("\n已用记事本打开「待确认.md」，可以先核对细节。")
    except Exception:
        print(f"\n（没能自动打开 {sync.PENDING_MD}，请自己去看）")

    ans = input("\n确认写入看板？输入 y 回车确认，直接回车取消：").strip().lower()
    if ans in ("y", "yes", "是", "确认"):
        sync.apply()
    else:
        print("\n已取消，待确认清单保留着，下次还能再写入。")
    pause()


if __name__ == "__main__":
    main()
