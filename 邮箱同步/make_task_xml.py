# -*- coding: utf-8 -*-
"""生成计划任务 XML（一次性的建任务工具，建完可以留着备用）"""
import os
import sys
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(BASE, "sync.py")

# 当前解释器的 pythonw 版（无控制台，跑计划任务不弹窗）
PYW = sys.executable.replace("python.exe", "pythonw.exe")
if not os.path.exists(PYW):
    PYW = sys.executable
start = (datetime.now() + timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%S")

XML = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>每30分钟扫描QQ邮箱，生成投递看板待确认清单</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <Repetition>
        <Interval>PT15M</Interval>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
      <StartBoundary>{start}</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay>
        <DaysInterval>1</DaysInterval>
      </ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <ExecutionTimeLimit>PT10M</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{PYW}</Command>
      <Arguments>-X utf8 &quot;{SCRIPT}&quot; scan --log</Arguments>
      <WorkingDirectory>{BASE}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""

out = os.path.join(BASE, "task.xml")
with open(out, "w", encoding="utf-16") as f:
    f.write(XML)
print("任务配置已生成：", out)
print("起始时间：", start)


def install():
    """交互式注册计划任务。中文提示全在这里，bat 里保持纯 ASCII。"""
    import subprocess

    print("\n" + "=" * 56)
    print("将创建一个 Windows 计划任务：")
    print("  名称：JobMailSync")
    print("  内容：每 15 分钟静默扫一次邮箱，结果记进 同步日志.txt")
    print("  作用：不用手动双击，看板会自己更新")
    print("=" * 56)
    print("不需要了随时可以删除：Win+R → taskschd.msc → 找到 JobMailSync → 右键删除")
    try:
        ans = input("\n继续创建？输入 y 回车确认，直接回车取消：").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return
    if ans not in ("y", "yes", "是", "确认"):
        print("已取消，什么都没改。")
        return

    r = subprocess.run(
        ["schtasks", "/Create", "/TN", "JobMailSync", "/XML", out, "/F"],
        capture_output=True,
    )
    text = (r.stdout + r.stderr).decode("gbk", "replace").strip()
    print()
    print(text)
    if r.returncode == 0:
        print("\n✅ 创建成功。之后每 15 分钟自动扫一次，不用管它。")
        print("   想立刻试一次：Win+R → taskschd.msc → 找到 JobMailSync → 右键「运行」")
    else:
        print("\n❌ 创建失败。常见原因：")
        print("   · 没有管理员权限 —— 右键这个文件「以管理员身份运行」再试")
        print("   · 系统禁止创建计划任务 —— 那就跳过这步，手动双击 1_扫描邮箱.bat 也一样用")


if __name__ == "__main__":
    if "--install" in sys.argv:
        install()
    else:
        print("\n（只生成了配置文件。要直接创建计划任务，运行：python make_task_xml.py --install）")
