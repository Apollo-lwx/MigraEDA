"""stdio MCP server for local JLCEDA / Altium conversion and LVS.

Install with ``pip install 'migraeda[mcp]'`` and launch ``migraeda-mcp``.
Design files stay on the machine that runs this process. Remote HTTP is not
provided: schematics and PCBs are design assets.
"""

import asyncio
import sys
import traceback
from collections.abc import Callable
from typing import Any

from migraeda.mcp_tools import (
    ToolError,
    render,
    run_convert,
    run_libinspect,
    run_pcbdiff,
    run_roundtrip,
    run_selfcheck,
    run_verify,
)


def build_mcp():
    """Create the FastMCP server. Requires the optional ``mcp`` extra."""
    from enum import Enum
    from typing import Annotated

    from mcp.server.fastmcp import FastMCP
    from pydantic import Field

    class ResponseFormat(str, Enum):
        MARKDOWN = "markdown"
        JSON = "json"

    Timeout = Annotated[int, Field(
        ge=1, le=600,
        description="本机解析超时（秒）。大板可调到 300，上限 600。",
    )]
    Limit = Annotated[int, Field(
        ge=1, le=50,
        description="差异条目最多返回多少条，其余只给数量。",
    )]
    Format = Annotated[ResponseFormat, Field(
        description="markdown 适合直接阅读，json 适合继续处理字段。",
    )]

    mcp = FastMCP("migraeda_mcp")

    async def _call(fn: Callable[[], dict[str, Any]], timeout: int, fmt: ResponseFormat) -> str:
        def finish() -> str:
            try:
                return render(fn(), fmt.value)
            except ToolError as exc:
                return f"Error: {exc}"
            except Exception as exc:
                traceback.print_exc(file=sys.stderr)
                return (
                    f"Error: {type(exc).__name__}: {exc}。"
                    "若是解析失败，先调用 migraeda_libinspect。"
                )

        try:
            return await asyncio.wait_for(asyncio.to_thread(finish), timeout=timeout)
        except TimeoutError:
            return (
                f"Error: 超过 {timeout} 秒仍未返回。"
                "把 timeout_seconds 调大（上限 600）。"
                "这次调用已停止等待，若机器仍在解析，等它结束后再重试。"
            )

    @mcp.tool(
        name="migraeda_convert",
        annotations={
            "title": "转换嘉立创与 Altium 设计",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def migraeda_convert(
        path: Annotated[str, Field(
            min_length=1,
            description="本机设计文件绝对路径。例：D:/boards/demo.eprj 或 D:/boards/demo.SchDoc",
        )],
        to: Annotated[str, Field(
            description="ad：.eprj → ASCII .SchDoc；adpcb：.eprj → ASCII .PcbDoc；eprj：.SchDoc → .eprj",
        )],
        output_dir: Annotated[str | None, Field(
            description="输出目录。省略时写到源文件旁边的 .migraeda/，该目录已被 git 忽略。",
        )] = None,
        verify: Annotated[bool, Field(
            description="转换后立即重解析并做引脚级 LVS。关掉后 grade 为 SKIPPED。",
        )] = True,
        panel_rows: Annotated[int, Field(
            ge=1, le=50,
            description="仅 to=adpcb：把板子纵向拼 N 行。原理图转换保持 1。",
        )] = 1,
        with_pcb: Annotated[str | None, Field(
            description="仅 to=eprj：把这份 .PcbDoc 的布局嵌进新的嘉立创工程。",
        )] = None,
        limit: Limit = 20,
        timeout_seconds: Timeout = 120,
        response_format: Format = ResponseFormat.MARKDOWN,
    ) -> str:
        """把嘉立创 .eprj 与 Altium .SchDoc / .PcbDoc 互相转换，并做引脚级闭环验证。

        不写 output_dir 时，产物写到源文件旁边的 .migraeda/。不会上传文件。
        grade 为 PASS 表示本次引脚连通一致，FAIL 表示有错位，SKIPPED 表示 verify=false。
        错位只返回 limit 条，字段是 ref、pin、a_net、b_net。

        Args:
            path: 本机绝对路径。
            to: ad、eprj 或 adpcb。
            output_dir: 可选输出目录。
            verify: 是否做闭环 LVS。
            panel_rows: 仅 adpcb 的纵向拼板行数。
            with_pcb: 仅 to=eprj 时嵌入的 .PcbDoc。
            limit: 错位列表上限，1 到 50。
            timeout_seconds: 超时秒数，1 到 600。
            response_format: markdown 或 json。

        Returns:
            str: markdown 或 json。json 含 grade、written、common_pins、mismatched、mismatches。

        Examples:
            - .eprj 转 Altium 原理图：to=ad
            - .eprj 转 Altium PCB：to=adpcb
            - .SchDoc 转回嘉立创：to=eprj
            - 两份现成文件对比用 migraeda_verify

        Error Handling:
            - 找不到文件时返回 Error，并提示传绝对路径
            - 解析失败时建议改调 migraeda_libinspect
        """
        return await _call(
            lambda: run_convert(
                path,
                to,
                output_dir=output_dir,
                verify=verify,
                panel_rows=panel_rows,
                with_pcb=with_pcb,
                limit=limit,
            ),
            timeout_seconds,
            response_format,
        )

    @mcp.tool(
        name="migraeda_verify",
        annotations={
            "title": "引脚级比对两份设计",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def migraeda_verify(
        file_a: Annotated[str, Field(min_length=1, description="第一份本机文件。例：D:/boards/a.eprj")],
        file_b: Annotated[str, Field(min_length=1, description="第二份本机文件。例：D:/boards/b.SchDoc")],
        limit: Limit = 20,
        timeout_seconds: Timeout = 120,
        response_format: Format = ResponseFormat.MARKDOWN,
    ) -> str:
        """比较两份 .eprj / .SchDoc / .PcbDoc 的引脚网络，不写设计文件。

        一边是 .eprj、另一边是 .PcbDoc 时，自动用 .eprj 里的 PCB 页网表，而不是原理图页。
        grade=FAIL 只说明公共引脚上有网络不一致，不表示文件损坏。

        Args:
            file_a: 第一份文件的绝对路径。
            file_b: 第二份文件的绝对路径。
            limit: 错位列表上限。
            timeout_seconds: 超时秒数。
            response_format: markdown 或 json。

        Returns:
            str: common_pins、mismatched、nets_matched，以及最多 limit 条 mismatches。

        Examples:
            - 官方导入之后核对：file_a=原始.SchDoc，file_b=导入后.eprj
            - 转文件用 migraeda_convert

        Error Handling:
            - 路径不存在返回 Error
            - 格式无法解析时建议先 migraeda_libinspect
        """
        return await _call(
            lambda: run_verify(file_a, file_b, limit=limit),
            timeout_seconds,
            response_format,
        )

    @mcp.tool(
        name="migraeda_pcbdiff",
        annotations={
            "title": "比对两份 PCB 几何",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def migraeda_pcbdiff(
        file_a: Annotated[str, Field(
            min_length=1,
            description="第一份 PCB：.PcbDoc 或含 PCB 页的 .eprj",
        )],
        file_b: Annotated[str, Field(
            min_length=1,
            description="第二份 PCB：.PcbDoc 或含 PCB 页的 .eprj",
        )],
        tol_mil: Annotated[float, Field(gt=0, le=100, description="位置容差，单位 mil。")] = 2.0,
        limit: Limit = 20,
        timeout_seconds: Timeout = 120,
        response_format: Format = ResponseFormat.MARKDOWN,
    ) -> str:
        """比对两份 PCB 的板框、元件、焊盘、过孔和铜皮统计。不写设计文件。

        接受 .PcbDoc（二进制或 ASCII）以及含 PCB 页的 .eprj。坐标系差异会先做刚体对齐。
        grade：元件或焊盘对不上、板框不同为 FAIL；只有铜皮统计或过孔数量不同为 WARN。

        Args:
            file_a: 第一份 PCB 的绝对路径。
            file_b: 第二份 PCB 的绝对路径。
            tol_mil: 位置容差，mil。
            limit: 差异列表上限。
            timeout_seconds: 超时秒数。
            response_format: markdown 或 json。

        Returns:
            str: grade、alignment、outline、位移列表（最多 limit 条）和省略数量。

        Examples:
            - 转换后的 ASCII .PcbDoc 对原始 .eprj 的 PCB 页
            - 引脚网络是否接错用 migraeda_verify

        Error Handling:
            - 文件不是 PCB 时返回 Error，说明只接受 .PcbDoc 或含 PCB 的 .eprj
        """
        return await _call(
            lambda: run_pcbdiff(file_a, file_b, tol_mil=tol_mil, limit=limit),
            timeout_seconds,
            response_format,
        )

    @mcp.tool(
        name="migraeda_roundtrip",
        annotations={
            "title": "往返转换并和原稿比对",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def migraeda_roundtrip(
        path: Annotated[str, Field(min_length=1, description="本机 .eprj 或 .SchDoc 绝对路径。")],
        output_dir: Annotated[str | None, Field(
            description="省略时写到源文件旁边的 .migraeda/roundtrip/。",
        )] = None,
        limit: Limit = 20,
        timeout_seconds: Timeout = 120,
        response_format: Format = ResponseFormat.MARKDOWN,
    ) -> str:
        """把 .eprj 或 .SchDoc 转出去再转回来，和原稿做引脚级比对。

        中间文件默认留在源文件旁边的 .migraeda/roundtrip/。
        .eprj 里若有 PCB 页，会再跑一遍 PCB 往返，结果放在 pcb 字段。
        不覆盖源文件。

        Args:
            path: 本机 .eprj 或 .SchDoc。
            output_dir: 可选输出目录。
            limit: 附注上限。
            timeout_seconds: 超时秒数。
            response_format: markdown 或 json。

        Returns:
            str: grade、written、common_pins、mismatched。含 PCB 时另有 pcb.grade。

        Examples:
            - 对一份 .eprj 做一次往返自证
            - 已经有两份不同来源的文件时，用 migraeda_verify

        Error Handling:
            - 后缀不是 .eprj / .SchDoc 时返回 Error
        """
        return await _call(
            lambda: run_roundtrip(path, output_dir=output_dir, limit=limit),
            timeout_seconds,
            response_format,
        )

    @mcp.tool(
        name="migraeda_libinspect",
        annotations={
            "title": "查看设计文件结构",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def migraeda_libinspect(
        path: Annotated[str, Field(
            min_length=1,
            description="本机库或设计文件。只返回结构元数据，适合外发求助。",
        )],
        timeout_seconds: Timeout = 120,
        response_format: Format = ResponseFormat.MARKDOWN,
    ) -> str:
        """读取一份库或设计文件的结构元数据，不返回网络和图形。

        输出可以外发求助。正文超过 8000 字会截断，并带上 truncated=true。

        Args:
            path: 本机文件绝对路径。
            timeout_seconds: 超时秒数。
            response_format: markdown 或 json。

        Returns:
            str: text 为结构说明，chars 为原文长度。

        Examples:
            - 转换报错前，先看容器是 OLE、SQLite 还是 ASCII
            - 判断两份设计是否等价用 migraeda_verify 或 migraeda_pcbdiff

        Error Handling:
            - 文件不存在返回 Error
        """
        return await _call(lambda: run_libinspect(path), timeout_seconds, response_format)

    @mcp.tool(
        name="migraeda_selfcheck",
        annotations={
            "title": "检查单份设计的可疑信号",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def migraeda_selfcheck(
        path: Annotated[str, Field(min_length=1, description="本机 .eprj、.SchDoc 或 .PcbDoc。")],
        pcb: Annotated[bool, Field(
            description="true 时对 .eprj 内的 PCB 页做保真清单，报告更长并会被截断。",
        )] = False,
        converted: Annotated[str | None, Field(
            description="可选。已经转出的 ASCII .PcbDoc，用来和 .eprj 内的 PCB 页对照。",
        )] = None,
        timeout_seconds: Timeout = 120,
        response_format: Format = ResponseFormat.MARKDOWN,
    ) -> str:
        """对单份文件做结构自检：悬空引脚、重复位号、网络名大小写冲突等。

        pcb=true 时只接受 .eprj，输出 PCB 保真清单。converted 可指向已转出的 .PcbDoc。
        长报告截断到 8000 字。不写文件。

        Args:
            path: 本机文件绝对路径。
            pcb: 是否检查 .eprj 内的 PCB 页。
            converted: 可选的已转换 .PcbDoc。
            timeout_seconds: 超时秒数。
            response_format: markdown 或 json。

        Returns:
            str: text 为自检正文。

        Examples:
            - 打开一份来历不明的 .SchDoc 之前先看有没有重复位号
            - 对照两份文件用 migraeda_verify

        Error Handling:
            - pcb=true 但文件不是 .eprj 时返回 Error
        """
        return await _call(
            lambda: run_selfcheck(path, pcb=pcb, converted=converted),
            timeout_seconds,
            response_format,
        )

    return mcp


def main() -> None:
    try:
        mcp = build_mcp()
    except ImportError:
        sys.stderr.write(
            "migraeda-mcp 需要可选依赖。执行：pip install \"migraeda[mcp]\"\n"
        )
        raise SystemExit(1)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
