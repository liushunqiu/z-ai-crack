"""DSML 工具调用协议:渲染器 + 流式解析器。

参考 ds2api-java/.../tool/DsmlToolFormatter.java 和 ToolCallStreamParser.java。

工作原理:
   DeepSeek 网页吃不下 OpenAI 的 tools 字段,所以把工具定义渲染成
   一段说明文本塞进 prompt,模型在文本里输出
       <|DSML|tool_calls>
         <|DSML|invoke name="X">
           <|DSML|parameter name="P"><![CDATA[V]]></|DSML|parameter>
         </|DSML|invoke>
       </|DSML|tool_calls>
   后端流式解析这段文本,产出 ToolCallStart / ToolCallDelta / ToolCallEnd
   事件,再由 adapter 转回 OpenAI 标准的 function_call 流。

边界处理(与 Java 完全一致):
- 兼容 <|DSML|...> 和 <DSML...> 两种写法
- 三态状态机:IDLE / IN_CODE_BLOCK / IDLE 中的 ``` / CAPTURING
- 防止 CAPTURING 超过 8192 字符未闭合(吃掉模型乱码当文本释放)
- IDLE 时遇到 "<" 后缀可能是工具调用前缀,需要保留缓冲
- CDATA 嵌套 ]]> 的转义
- 文件写入工具的 heredoc / echo / printf 内容提取
- 参数值的类型推断(JSON object/array、true/false、数字、字符串)
"""
from __future__ import annotations

import json
import re
import uuid
import xml.etree.ElementTree as ET
from .models import (
    InternalStreamEvent,
    TextDelta,
    ToolCallDelta,
    ToolCallEnd,
    ToolCallStart,
)

# ──────────────────────────────────────────────────────────────
# DSML 渲染:tool_calls(JSON 数组) -> DSML 文本
# ──────────────────────────────────────────────────────────────


def tool_calls_to_dsml(tool_calls: list[dict] | None) -> str:
    if not tool_calls:
        return ""
    blocks = [b for b in (_format_single_tool_call(tc) for tc in tool_calls) if b]
    if not blocks:
        return ""
    return "<|DSML|tool_calls>\n" + "\n".join(blocks) + "\n</|DSML|tool_calls>"


def _format_single_tool_call(call: dict) -> str:
    if not isinstance(call, dict):
        return ""
    func = call.get("function") or {}
    name = (func.get("name") or call.get("name") or "").strip()
    args_raw = func.get("arguments")
    if args_raw is None:
        args_raw = call.get("arguments")
    if args_raw is None:
        args_raw = call.get("input")
    if not name:
        return ""
    params = _format_parameters_for_prompt(args_raw)
    attr = _escape_xml_attr(name)
    if not params:
        return f'  <|DSML|invoke name="{attr}"></|DSML|invoke>'
    return f'  <|DSML|invoke name="{attr}">\n{params}\n  </|DSML|invoke>'


def _format_parameters_for_prompt(args_raw) -> str:
    if args_raw is None:
        return ""
    if isinstance(args_raw, str):
        text = args_raw.strip()
        if not text:
            return ""
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return _render_object_params(parsed, "    ")
        except json.JSONDecodeError:
            pass
        return f'    <|DSML|parameter name="content">{_render_cdata(text)}</|DSML|parameter>'
    if isinstance(args_raw, dict):
        if not args_raw:
            return ""
        return _render_object_params(args_raw, "    ")
    if isinstance(args_raw, list):
        return _render_array_params(args_raw, "    ")
    return f'    <|DSML|parameter name="value">{_render_cdata(str(args_raw))}</|DSML|parameter>'


def _render_object_params(obj: dict, indent: str) -> str:
    lines = []
    for k, v in obj.items():
        rendered = _render_parameter_node(k, v, indent)
        if rendered:
            lines.append(rendered)
    return "\n".join(lines)


def _render_array_params(arr: list, indent: str) -> str:
    lines = []
    for item in arr:
        rendered = _render_parameter_node("item", item, indent)
        if rendered:
            lines.append(rendered)
    return "\n".join(lines)


def _render_parameter_node(name: str, value, indent: str) -> str:
    if not name or not name.strip():
        return ""
    name = name.strip()
    attr = _escape_xml_attr(name)

    if value is None:
        return f'{indent}<|DSML|parameter name="{attr}"></|DSML|parameter>'

    if isinstance(value, dict):
        if not value:
            return f'{indent}<|DSML|parameter name="{attr}"></|DSML|parameter>'
        inner = _render_object_params(value, indent + "  ")
        if not inner.strip():
            return f'{indent}<|DSML|parameter name="{attr}"></|DSML|parameter>'
        return f'{indent}<|DSML|parameter name="{attr}">\n{inner}\n{indent}</|DSML|parameter>'

    if isinstance(value, list):
        if not value:
            return f'{indent}<|DSML|parameter name="{attr}"></|DSML|parameter>'
        item_lines = []
        for item in value:
            r = _render_parameter_node("item", item, indent + "  ")
            if r:
                item_lines.append(r)
        if not item_lines:
            return f'{indent}<|DSML|parameter name="{attr}"></|DSML|parameter>'
        return (f'{indent}<|DSML|parameter name="{attr}">\n'
                + "\n".join(item_lines)
                + f'\n{indent}</|DSML|parameter>')

    if isinstance(value, str):
        text = _render_cdata(value)
    elif isinstance(value, bool):
        text = "true" if value else "false"
    else:
        text = _escape_xml_text(str(value))
    return f'{indent}<|DSML|parameter name="{attr}">{text}</|DSML|parameter>'


def _render_cdata(text: str) -> str:
    if not text:
        return ""
    if "]]>" in text:
        return "<![CDATA[" + text.replace("]]>", "]]]]><![CDATA[>") + "]]>"
    return f"<![CDATA[{text}]]>"


def _escape_xml_attr(text: str) -> str:
    return (text.replace("&", "&amp;").replace('"', "&quot;")
                .replace("<", "&lt;").replace(">", "&gt;"))


def _escape_xml_text(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ──────────────────────────────────────────────────────────────
# 工具说明文本:渲染 tools 数组成可塞进 prompt 的提示块
#   照搬 PromptCompatService.injectToolDefinitions + buildToolCallInstructions
# ──────────────────────────────────────────────────────────────

_TOOL_CALL_INSTRUCTIONS = """## TOOL CALL FORMAT

To call a tool, emit a single block in this exact shape:

<|DSML|tool_calls>
  <|DSML|invoke name="TOOL_NAME">
    <|DSML|parameter name="PARAM"><![CDATA[VALUE]]></|DSML|parameter>
  </|DSML|invoke>
</|DSML|tool_calls>

You may write a brief one-sentence intent BEFORE the block when it helps (e.g. "Running tests now."). Do NOT put prose AFTER the block, and do NOT wrap the block in markdown fences.

## RULES

1. **One block per turn** — if you need multiple tool calls, put several <|DSML|invoke> inside the same <|DSML|tool_calls>.
2. **Strings → CDATA** — wrap every string value in <![CDATA[...]]>, including code, paths, and file content.
3. **Objects / arrays → nested XML** — never raw JSON. Objects become nested <|DSML|parameter>; arrays use <item> children.
4. **Numbers / booleans / null → plain text** — no quotes, no CDATA.
5. **Use the exact parameter names from the tool schema** — do not invent or rename fields.
6. **Write files via the Write tool, never via Bash heredoc / echo / printf** — the Write tool's `content` parameter is raw file content, not shell syntax.
7. **Edit files via apply_patch (unified diff) or Edit** — do not use sed / awk in Bash.
"""


def _example_params(name: str) -> str | None:
    """与 Java getExampleParams 对齐,给常见工具名提供示例。"""
    body_map = {
        ("Bash", "execute_command", "exec_command"):
            f'  <|DSML|invoke name="{name}">\n'
            f'    <|DSML|parameter name="command"><![CDATA[pwd]]></|DSML|parameter>\n'
            f'  </|DSML|invoke>',
        ("Read", "read_file"):
            f'  <|DSML|invoke name="{name}">\n'
            f'    <|DSML|parameter name="file_path"><![CDATA[README.md]]></|DSML|parameter>\n'
            f'  </|DSML|invoke>',
        ("Glob", "list_files"):
            f'  <|DSML|invoke name="{name}">\n'
            f'    <|DSML|parameter name="pattern"><![CDATA[**/*.go]]></|DSML|parameter>\n'
            f'    <|DSML|parameter name="path"><![CDATA[.]]></|DSML|parameter>\n'
            f'  </|DSML|invoke>',
        ("search_files",):
            f'  <|DSML|invoke name="{name}">\n'
            f'    <|DSML|parameter name="query"><![CDATA[tool call parser]]></|DSML|parameter>\n'
            f'  </|DSML|invoke>',
        ("Write", "write_to_file"):
            f'  <|DSML|invoke name="{name}">\n'
            f'    <|DSML|parameter name="file_path"><![CDATA[notes.txt]]></|DSML|parameter>\n'
            f'    <|DSML|parameter name="content"><![CDATA[Hello world]]></|DSML|parameter>\n'
            f'  </|DSML|invoke>',
        ("apply_patch",):
            f'  <|DSML|invoke name="{name}">\n'
            f'    <|DSML|parameter name="patch"><![CDATA['
            f'--- a/README.md\n'
            f'+++ b/README.md\n'
            f'@@ -1,3 +1,3 @@\n'
            f' old line\n'
            f'-removed\n'
            f'+added\n'
            f']]></|DSML|parameter>\n'
            f'  </|DSML|invoke>',
        ("Edit",):
            f'  <|DSML|invoke name="{name}">\n'
            f'    <|DSML|parameter name="file_path"><![CDATA[README.md]]></|DSML|parameter>\n'
            f'    <|DSML|parameter name="old_string"><![CDATA[foo]]></|DSML|parameter>\n'
            f'    <|DSML|parameter name="new_string"><![CDATA[bar]]></|DSML|parameter>\n'
            f'  </|DSML|invoke>',
    }
    for names, body in body_map.items():
        if name in names:
            return body
    return None


def _build_tool_examples(tool_names: list[str]) -> str:
    examples: list[str] = []
    basic_body = next((b for n in tool_names if (b := _example_params(n))), None)
    if basic_body:
        examples.append(
            "Example A — Single tool:\n<|DSML|tool_calls>\n"
            + basic_body
            + "\n</|DSML|tool_calls>"
        )
    parallel = [b for n in tool_names if (b := _example_params(n))][:2]
    if len(parallel) >= 2:
        examples.append(
            "Example B — Two tools in parallel:\n<|DSML|tool_calls>\n"
            + "\n".join(parallel)
            + "\n</|DSML|tool_calls>"
        )
    if not examples:
        return ""
    return "【CORRECT EXAMPLES】:\n\n" + "\n\n".join(examples) + "\n\n"


def _extract_tool_name(tool: dict) -> str:
    n = (tool.get("name") or "").strip()
    if n:
        return n
    func = tool.get("function") or {}
    return (func.get("name") or "").strip()


def _extract_tool_desc(tool: dict) -> str:
    d = (tool.get("description") or "").strip()
    if d:
        return d
    func = tool.get("function") or {}
    d = (func.get("description") or "").strip()
    return d or "No description available"


def _extract_tool_schema(tool: dict) -> dict | None:
    for k in ("parameters", "input_schema", "inputSchema", "schema"):
        v = tool.get(k)
        if v is not None:
            return v
    func = tool.get("function") or {}
    for k in ("parameters", "input_schema", "inputSchema", "schema"):
        v = func.get(k)
        if v is not None:
            return v
    return None


_TOOL_USAGE_NOTES: dict[str, str] = {
    # codex 的 update_plan 注册完计划后,plan 已经在 UI 左侧显示给用户。
    # DeepSeek 默认会"礼貌地"用自然语言复述一遍并问用户要不要开始,把 agent
    # 流程拖死在第 0 步。这里明确告诉它:注册=立即执行。
    "update_plan": (
        "IMPORTANT: After calling update_plan, the plan is already shown to the user in the UI. "
        "You MUST immediately proceed to execute step 1 via another tool call in the SAME response. "
        "Do NOT restate, summarize, or describe the plan in natural language. "
        "Do NOT ask the user to confirm before proceeding."
    ),
    "apply_patch": (
        "Use apply_patch to edit existing files. Provide unified diff format in the 'patch' parameter. "
        "Do NOT use sed, awk, or Bash commands to edit files."
    ),
}


def format_tools_section(tools: list[dict]) -> str:
    """把工具数组渲染成一段说明文本,塞到系统提示后面。"""
    if not tools:
        return ""
    names: list[str] = []
    schemas: list[str] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        name = _extract_tool_name(tool)
        if not name:
            continue
        desc = _extract_tool_desc(tool)
        params = _extract_tool_schema(tool)
        params_str = json.dumps(params, ensure_ascii=False) if params else "{}"
        names.append(name)
        note = _TOOL_USAGE_NOTES.get(name)
        block = f"Tool: {name}\nDescription: {desc}\nParameters: {params_str}\n"
        if note:
            block += f"Usage Note: {note}\n"
        schemas.append(block)

    if not names:
        return ""
    return (
        "\n\nYou have access to these tools:\n\n"
        f"Available tool names: {', '.join(names)}\n"
        "Use one of these names verbatim in <|DSML|invoke name=\"...\">; "
        "do not invent, rename, or substitute tool names.\n\n"
        + "\n".join(schemas) + "\n"
        + _TOOL_CALL_INSTRUCTIONS
        + "\n"
        + _build_tool_examples(names)
    )


# ──────────────────────────────────────────────────────────────
# 流式解析器:状态机
# ──────────────────────────────────────────────────────────────

_MAX_CAPTURE_LEN = 8192

_CODE_FENCE = re.compile(r"```")
# 支持标签末尾有 | 的格式：<|DSML|tool_calls|> 或 <|DSML|tool_calls>
_TOOL_CALLS_START = re.compile(r"<\|?DSML\|?tool_calls\s*\|?>", re.IGNORECASE)
_TOOL_CALLS_END = re.compile(r"</\|?DSML\|?tool_calls\s*\|?>", re.IGNORECASE)
_INVOKE_START = re.compile(r'<\|?DSML\|?invoke\s+name="([^"]+)"\s*\|?>', re.IGNORECASE)
_INVOKE_END = re.compile(r"</\|?DSML\|?invoke\s*\|?>", re.IGNORECASE)
_PARAM_START = re.compile(r'<\|?DSML\|?parameter\s+name="([^"]+)"[^>]*\|?>', re.IGNORECASE)
_PARAM_END = re.compile(r"</\|?DSML\|?parameter\s*\|?>", re.IGNORECASE)

# Heredoc 提取 —— 模型有时会把内容包在 shell 命令里返回
_HEREDOC_CAT = re.compile(
    r"cat\s+>\s+\S+\s+<<\s*['\"]?(\w+)['\"]?\s*\n([\s\S]*?)\n\1\s*$",
    re.MULTILINE,
)
_HEREDOC_ECHO = re.compile(r"^echo\s+['\"](.*)['\"]\s*>\s*\S+$", re.DOTALL)
_HEREDOC_PRINTF = re.compile(r"^printf\s+['\"](.*)['\"]\s*>\s*\S+$", re.DOTALL)

_PARTIAL_TAG_PREFIXES = (
    "<|dsml|", "<|dsm", "<|ds", "<|d", "<|",
    "<![cdata[", "</", "<!", "<",
)


class _State:
    IDLE = "IDLE"
    IN_CODE_BLOCK = "IN_CODE_BLOCK"
    CAPTURING = "CAPTURING"


class ToolCallStreamParser:
    """流式解析器,边喂边吐事件。

    用法:
        parser = ToolCallStreamParser()
        for delta in upstream_text_stream:
            for event in parser.feed(delta):
                yield event
        for event in parser.flush():
            yield event
    """

    def __init__(self) -> None:
        self._state = _State.IDLE
        self._buffer = ""
        self._had_tool_call = False

    @property
    def had_tool_call(self) -> bool:
        return self._had_tool_call

    def feed(self, chunk: str) -> list[InternalStreamEvent]:
        if not chunk:
            return []
        self._buffer += chunk
        return self._drain()

    def flush(self) -> list[InternalStreamEvent]:
        """流结束时调用:把残余缓冲当文本释放,重置状态。"""
        events: list[InternalStreamEvent] = []
        if self._buffer:
            events.append(TextDelta(self._buffer))
        self.reset()
        return events

    def reset(self) -> None:
        self._state = _State.IDLE
        self._buffer = ""

    # ──────────── 状态机驱动 ────────────

    def _drain(self) -> list[InternalStreamEvent]:
        events: list[InternalStreamEvent] = []
        progress = True
        while progress and self._buffer:
            progress = False
            if self._state == _State.IDLE:
                progress = self._process_idle(events)
            elif self._state == _State.IN_CODE_BLOCK:
                progress = self._process_code_block(events)
            elif self._state == _State.CAPTURING:
                progress = self._process_capturing(events)
        return events

    def _process_idle(self, events: list[InternalStreamEvent]) -> bool:
        text = self._buffer
        fence_m = _CODE_FENCE.search(text)
        tc_m = _TOOL_CALLS_START.search(text)

        fence_idx = fence_m.start() if fence_m else float("inf")
        tc_idx = tc_m.start() if tc_m else float("inf")

        if fence_idx < tc_idx and fence_m:
            if fence_idx > 0:
                events.append(TextDelta(text[:fence_idx]))
            self._buffer = text[fence_m.end():]
            self._state = _State.IN_CODE_BLOCK
            return True
        if tc_m:
            if tc_idx > 0:
                events.append(TextDelta(text[:tc_idx]))
            self._buffer = text[tc_m.end():]
            self._state = _State.CAPTURING
            return True

        # 都没找到完整的起始标记。释放"安全"的部分,保留可能是部分标签的尾巴
        safe_end = _find_safe_end(text)
        if safe_end > 0:
            events.append(TextDelta(text[:safe_end]))
            self._buffer = text[safe_end:]
            return True
        return False

    def _process_code_block(self, events: list[InternalStreamEvent]) -> bool:
        m = _CODE_FENCE.search(self._buffer)
        if not m:
            return False
        if m.start() > 0:
            events.append(TextDelta(self._buffer[:m.start()]))
        self._buffer = self._buffer[m.end():]
        self._state = _State.IDLE
        return True

    def _process_capturing(self, events: list[InternalStreamEvent]) -> bool:
        text = self._buffer
        m = _TOOL_CALLS_END.search(text)
        if m:
            captured = text[:m.start()]
            self._parse_and_emit_tool_calls(captured, events)
            self._buffer = text[m.end():]
            self._state = _State.IDLE
            return True
        if len(text) > _MAX_CAPTURE_LEN:
            # 溢出:当作普通文本释放,避免吃掉真实内容
            events.append(TextDelta(text))
            self._buffer = ""
            self._state = _State.IDLE
            return True
        return False

    # ──────────── DSML 解析 ────────────

    def _parse_and_emit_tool_calls(
        self, captured: str, events: list[InternalStreamEvent]
    ) -> None:
        pos = 0
        tool_index = 0
        for m in _INVOKE_START.finditer(captured):
            if m.start() < pos:
                continue
            tool_name = m.group(1)
            call_id = f"call_{uuid.uuid4().hex[:8]}"
            self._had_tool_call = True
            events.append(ToolCallStart(call_id, tool_name, tool_index))

            invoke_start = m.end()
            end_m = _INVOKE_END.search(captured, invoke_start)
            if end_m:
                body = captured[invoke_start:end_m.start()]
                pos = end_m.end()
            else:
                body = captured[invoke_start:]
                pos = len(captured)

            args_json = _parse_invoke_body_to_json(body)
            if args_json and args_json != "{}":
                events.append(ToolCallDelta(call_id, tool_index, args_json))

            events.append(ToolCallEnd(call_id, tool_index))
            tool_index += 1


def _find_safe_end(text: str) -> int:
    """寻找可以放心当 TextDelta 释放的截断点;返回前缀长度。

    如果文本末尾形似 "<", "<|", "<|D" 等可能是工具调用前缀的字符,
    保留在 buffer 等下一轮拼接。
    """
    last_lt = text.rfind("<")
    if last_lt < 0:
        return len(text)
    suffix = text[last_lt:]
    if not suffix:
        return last_lt
    lower = suffix.lower()
    if any(lower.startswith(p) for p in _PARTIAL_TAG_PREFIXES):
        return last_lt
    return len(text)


# ──────────────────────────────────────────────────────────────
# DSML invoke body -> JSON arguments
# ──────────────────────────────────────────────────────────────

def _parse_invoke_body_to_json(body: str) -> str:
    params = _parse_parameters_structured(body)
    if not params:
        return "{}"
    # 类型推断 & JSON 字符串解包,再做"数组包装"展平
    processed = {
        k: _normalize_array_wrapper(k, _unwrap_value(v))
        for k, v in params.items()
    }
    try:
        return json.dumps(processed, ensure_ascii=False)
    except Exception:
        return "{}"


def _parse_parameters_structured(body: str) -> dict:
    """优先用 XML 解析器(支持嵌套);失败回退到正则平铺。"""
    # 把 <|DSML|...> 标签替换成普通 XML 标签,让 ET 能识别
    cleaned = body.replace("<|DSML|", "<").replace("</|DSML|", "</")
    sanitized = _sanitize_xml_content(cleaned)
    xml_text = f"<root>{sanitized}</root>"
    result: dict = {}
    try:
        root = ET.fromstring(xml_text)
        _parse_child_parameters(root, result)
    except ET.ParseError:
        return _parse_parameters_flat(body)

    # 后处理:抽取 heredoc / echo / printf 实际内容
    for k, v in list(result.items()):
        if isinstance(v, str):
            result[k] = _extract_heredoc_content(v)
    return result


def _parse_child_parameters(parent: ET.Element, result: dict) -> None:
    for elem in list(parent):
        tag = elem.tag.lower()
        if tag not in ("parameter", "item"):
            # 非标准标签(如 <step>,<status>):当作 key-value 对,不丢弃
            name = elem.attrib.get("name", "").strip() or tag
            result[name] = _xml_node_to_value(elem)
            continue
        name = elem.attrib.get("name", "").strip()
        if not name and tag == "item":
            name = "item"
        if not name:
            continue

        has_nested = any(
            (c.tag.lower() in ("parameter", "item"))
            for c in list(elem)
        )
        if not has_nested:
            text = _element_text(elem)
            result[name] = _strip_cdata(text)
            continue

        # 判断子节点是否全部是 item -> 数组,否则当 object
        items: list = []
        nested: dict = {}
        for child in list(elem):
            ctag = child.tag.lower()
            if ctag not in ("parameter", "item"):
                continue
            child_name = child.attrib.get("name", "").strip()
            if not child_name and ctag == "item":
                child_name = "item"
            if ctag == "item" or child_name == "item":
                inner: dict = {}
                _parse_child_parameters(child, inner)
                items.append(inner if inner else _element_text(child))
            else:
                inner_map: dict = {}
                _parse_child_parameters(child, inner_map)
                nested[child_name] = inner_map if inner_map else _element_text(child)
        if items:
            existing = result.get(name)
            if isinstance(existing, list):
                existing.extend(items)
            else:
                result[name] = items
        elif nested:
            result[name] = nested


def _element_text(elem: ET.Element) -> str:
    parts = []
    if elem.text:
        parts.append(elem.text)
    for c in list(elem):
        if c.tail:
            parts.append(c.tail)
    return "".join(parts).strip()


def _parse_parameters_flat(body: str) -> dict:
    """正则平铺解析,作为 XML 解析失败的回退。"""
    params: dict = {}
    pos = 0
    while True:
        m = _PARAM_START.search(body, pos)
        if not m:
            break
        name = m.group(1)
        value_start = m.end()
        end_m = _PARAM_END.search(body, value_start)
        if end_m:
            value = _strip_cdata(body[value_start:end_m.start()])
            pos = end_m.end()
        else:
            value = _strip_cdata(body[value_start:])
            pos = len(body)
        params[name] = _extract_heredoc_content(value)
        if pos >= len(body):
            break
    return params


def _sanitize_xml_content(content: str) -> str:
    """逐字符状态机:处理 CDATA 内嵌 ]]> 的拆分,转义裸 & 和野生 <。

    与 Java 的 sanitizeXmlContent 行为一致。
    """
    if not content:
        return ""
    out: list[str] = []
    i = 0
    in_tag = False
    in_cdata = False
    n = len(content)
    while i < n:
        c = content[i]
        # CDATA 开始
        if not in_tag and not in_cdata and content.startswith("<![CDATA[", i):
            in_cdata = True
            out.append("<![CDATA[")
            i += 9
            continue
        # CDATA 结束
        if in_cdata and content.startswith("]]>", i):
            in_cdata = False
            out.append("]]>")
            i += 3
            continue
        # CDATA 内部嵌套 ]]> -> 拆分
        if in_cdata:
            if c == "]" and content.startswith("]]>", i):
                # 上面已经被外层 startswith 抓走了,理论上不会到这里
                out.append("]]]]><![CDATA[>")
                i += 3
                continue
            out.append(c)
            i += 1
            continue
        # 进入 tag
        if not in_tag and c == "<":
            close_idx = content.find(">", i)
            if close_idx > i:
                inner = content[i + 1:close_idx]
                if inner and (inner[0].isalpha() or inner[0] in "/!?"):
                    in_tag = True
                    out.append(c)
                    i += 1
                    continue
            out.append("&lt;")
            i += 1
            continue
        if in_tag and c == ">":
            in_tag = False
            out.append(c)
            i += 1
            continue
        # 转义野生 &
        if c == "&" and not in_tag:
            semi = content.find(";", i)
            if 0 < semi - i < 10:
                entity = content[i + 1:semi]
                if re.fullmatch(r"[a-zA-Z]+|#\d+|#x[0-9a-fA-F]+", entity):
                    out.append(c)
                    i += 1
                    continue
            out.append("&amp;")
            i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _strip_cdata(s: str) -> str:
    if not s:
        return ""
    t = s.strip()
    if t.startswith("<![CDATA["):
        t = t[9:]
    # 支持 ]]> 和 ]]>| 两种结尾格式
    if t.endswith("]]>|"):
        t = t[:-4]
    elif t.endswith("]]>"):
        t = t[:-3]
    return t


def _extract_heredoc_content(value: str) -> str:
    """从 shell heredoc / echo / printf 字面量里抽出实际内容。

    模型经常输出
        cat > FILE << 'TAG'
        ...real content...
        TAG
    这种 shell 脚本而不是直接给内容,这里把它还原。
    """
    if not value:
        return value
    trimmed = value.strip()

    m = _HEREDOC_CAT.search(trimmed)
    if m:
        return m.group(2)
    m = _HEREDOC_ECHO.match(trimmed)
    if m:
        return m.group(1)
    m = _HEREDOC_PRINTF.match(trimmed)
    if m:
        return m.group(1)
    return value


def _try_parse_item_array(text: str):
    """CDATA 里被塞了一串 <item>...</item> 时,还原成 list。

    DeepSeek 经常违反 DSML "数组用 <item> 子节点" 的规则,把整段 item 序列
    包进 CDATA 当字符串塞进来。这里识别并恢复为真数组,避免下游(如 codex
    的 update_plan)拿到字符串报错。
    返回 None 表示该字符串不是 item 序列,交给后续类型推断。
    """
    sanitized = _sanitize_xml_content(text)
    try:
        root = ET.fromstring(f"<root>{sanitized}</root>")
    except ET.ParseError:
        return None
    children = list(root)
    if not children:
        return None
    if not all(c.tag.lower() == "item" for c in children):
        return None
    return [_xml_node_to_value(c) for c in children]


def _xml_node_to_value(elem: ET.Element):
    """把任意 XML 元素递归转为 Python 值(标量 / dict / list)。"""
    children = list(elem)
    if not children:
        return _unwrap_value(_strip_cdata(_element_text(elem)))
    # 所有子节点都叫 item -> 数组
    if all(c.tag.lower() == "item" for c in children):
        return [_xml_node_to_value(c) for c in children]
    obj: dict = {}
    for c in children:
        obj[c.tag] = _xml_node_to_value(c)
    return obj


def _unwrap_value(value):
    """字符串值的类型推断:JSON / <item> 数组 / bool / 数字 / 字符串。"""
    if not isinstance(value, str):
        return value
    trimmed = value.strip()
    if not trimmed:
        return value
    if (trimmed.startswith("{") and trimmed.endswith("}")) or \
       (trimmed.startswith("[") and trimmed.endswith("]")):
        try:
            return json.loads(trimmed)
        except (json.JSONDecodeError, ValueError):
            pass
    # 兜底:模型把数组写成 <item>...</item> 序列塞进 CDATA(常见于 update_plan 等)
    if trimmed.lower().startswith("<item"):
        parsed = _try_parse_item_array(trimmed)
        if parsed is not None:
            return parsed
    low = trimmed.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    if low == "null":
        return None
    # 数字
    try:
        if "." in trimmed:
            return float(trimmed)
        return int(trimmed)
    except ValueError:
        pass
    return value


_ARRAY_WRAPPER_KEYS = frozenset({
    "items", "list", "array", "values", "data", "elements", "entries",
})


def _normalize_array_wrapper(param_name: str, value):
    """展平 {"items": [...]} 这种"单键 dict 包数组"。

    DeepSeek 在数组类型参数上偶尔会自作主张包一层(常见为 "items",有时是
    与参数名同名的键)。codex / OpenAI 工具调用按 schema 校验:期望 sequence
    收到 map 直接报 "expected a sequence"。这里在不依赖 schema 信息的前提下
    做最小修正:只展开已知包装键名或与参数名同名的情况,避免误伤业务 dict。
    """
    if not isinstance(value, dict) or len(value) != 1:
        return value
    ((k, v),) = value.items()
    if not isinstance(v, list):
        return value
    if k.lower() in _ARRAY_WRAPPER_KEYS or k.lower() == param_name.lower():
        return v
    return value
