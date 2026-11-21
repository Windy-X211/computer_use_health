import datetime
import json
import logging
import urllib.error
import urllib.request

from health_guard.state import UsageState

log = logging.getLogger("health_guard.gatekeeper")


class GatekeeperError(Exception):
    pass


_SYSTEM_PROMPT = """\
你是电脑使用健康管家的"AI 门卫"。用户在当前受限时段请求临时使用电脑。
你需要根据:当前时间、用户的理由、以及用户自己设定的使用规则,判断是否放行。
规则:
- 仅当理由合理且紧急时(如工作/学习紧急需求、必须处理的事务)才放行。
- 如果理由模糊、借口明显(如"就是想玩""休息一下"),应拒绝。
- 如果放行,给出一个合理的使用时长(分钟),不得超过用户设定的最大值。
- 使用中文回复。
必须只输出一个 JSON 对象,格式如下,不要输出任何其他内容:
{"allow": true/false, "minutes": 数字, "reason": "你的判断理由"}"""


def _build_user_prompt(cfg: dict, state: UsageState, reason: str) -> str:
    now = datetime.datetime.now()
    dur = cfg.get("duration", {})
    gk = cfg.get("gatekeeper", {})
    daily_used_min = state.daily_used_seconds // 60
    context = (
        f"当前时间:{now.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"今日已使用:{daily_used_min} 分钟\n"
        f"每日上限:{dur.get('daily_limit_minutes', 240)} 分钟\n"
        f"单次会话上限:{dur.get('session_limit_minutes', 60)} 分钟\n"
        f"AI 门卫最大放行时长:{gk.get('max_grant_minutes', 60)} 分钟\n"
        f"默认放行时长:{gk.get('default_grant_minutes', 15)} 分钟\n"
        f"用户的理由:{reason}\n"
        "请判断是否放行,以及放行时长(分钟)。"
    )
    return context


def _extract_json(text: str) -> dict:
    text = text.strip()
    if not text:
        raise GatekeeperError("AI 返回为空")
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise GatekeeperError("AI 返回格式错误(未包含 JSON)")
    candidate = text[start : end + 1]
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise GatekeeperError(f"AI 返回 JSON 解析失败: {exc}")
    return data


def evaluate_request(cfg: dict, state: UsageState, reason: str) -> dict:
    gk = cfg.get("gatekeeper", {})
    if not gk.get("enabled"):
        raise GatekeeperError("AI 门卫未启用")
    api_key = gk.get("api_key", "").strip()
    if not api_key or set(api_key) == {"*"}:
        raise GatekeeperError("未配置 API Key,请在设置中填写")
    base_url = gk.get("base_url", "https://api.openai.com/v1").rstrip("/")
    model = gk.get("model", "gpt-4o-mini")
    timeout = int(gk.get("timeout_seconds", 20))
    temperature = float(gk.get("temperature", 0.2))
    max_minutes = int(gk.get("max_grant_minutes", 60))
    default_minutes = int(gk.get("default_grant_minutes", 15))

    user_prompt = _build_user_prompt(cfg, state, reason)
    payload = {
        "model": model,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    }
    url = f"{base_url}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp_body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8")[:300]
        except Exception:
            pass
        raise GatekeeperError(f"AI 请求失败 HTTP {exc.code}: {detail}")
    except Exception as exc:
        raise GatekeeperError(f"AI 请求失败: {exc}")

    try:
        data = json.loads(resp_body)
    except json.JSONDecodeError as exc:
        raise GatekeeperError(f"AI 响应解析失败: {exc}")

    content = (
        data.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
    )
    decision = _extract_json(content)

    allow = bool(decision.get("allow", False))
    minutes = decision.get("minutes", default_minutes)
    try:
        minutes = int(minutes)
    except (TypeError, ValueError):
        minutes = default_minutes
    if not allow:
        minutes = 0
    minutes = max(0, min(minutes, max_minutes))
    result_reason = str(decision.get("reason", "")).strip()[:300]
    return {
        "allow": allow,
        "minutes": minutes,
        "reason": result_reason,
        "raw": content[:500],
    }
