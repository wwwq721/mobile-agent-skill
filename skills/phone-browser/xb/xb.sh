#!/bin/sh
# 快速入口。省略 --op-id 会创建新操作；明确重试时传回原编号。
# xb [--op-id ID] js '表达式' [秒] | open [--new] 'url' | click '选择器或ref' | fill '选择器' '值'
# xb text [all|'选择器'] | snapshot [--all|--sel|--text|--raw|JSON] | status [-v]
#
# 输出默认走 xbfmt.py 压缩：snapshot 只回「序号+标签+ref」，正文和 CSS 路径按需再取。
#
# 等待预算规则：桥的任务时限 = 用户给的值（不变）；curl 的网络等待 = 任务时限 + MARGIN。
# 两者相等时，桥刚结束等待、结果还没写完，curl 就先断开（退出 28、无正文）。
B=http://127.0.0.1:8765
D=$(cd "$(dirname "$0")/.." && pwd)
MARGIN=2
op_id=

usage() {
    echo 'usage: xb [--op-id ID] js|open|text|snapshot|click|fill|status ...' >&2
    exit 2
}

fmt() { python3 "$D/xb/xbfmt.py" "$@"; }
# emit <fmt子命令> <信封> <curl退出码>：先格式化再从原退出码退出（错误正文不能被吞掉）
emit() {
    # $1 可能带参数（如 "text --all"），这里必须让 shell 再拆一次词
    printf '%s\n' "$2" | fmt $1
    [ "$3" -eq 0 ] || exit "$3"
}

if [ "${1:-}" = --op-id ]; then
    [ "$#" -ge 3 ] || usage
    op_id=$2
    case "$op_id" in ''|*[!a-zA-Z0-9._-]*) usage ;; esac
    [ "${#op_id}" -le 128 ] || usage
    shift 2
fi

request() (
    if [ -n "$op_id" ]; then set -- -H "X-Minis-Op-Id: $op_id" "$@"; fi
    # Probe the installed curl without submitting a command. Never replay a failed request.
    if curl --fail-with-body --version >/dev/null 2>&1; then
        exec curl -sS --fail-with-body -w '\n' "$@"
    fi
    reply=$(mktemp) || exit 1
    trap 'rm -f "$reply"' 0
    trap 'exit 1' HUP INT TERM
    status=$(curl -sS -o "$reply" -w '%{http_code}' "$@")
    transport=$?
    cat "$reply" || exit 1
    printf '\n'
    [ "$transport" -eq 0 ] || exit "$transport"
    case "$status" in 2??) exit 0 ;; *) exit 22 ;; esac
)

json_args() {
    python3 -c 'import json,sys; args=sys.argv[1:]; print(json.dumps(dict(zip(args[::2],args[1::2]))))' "$@"
}

# 接受桥允许的有限秒数格式，网络等待另加余量。
net_wait() {
    LC_ALL=C awk -v t="${1:-}" -v m="$MARGIN" 'BEGIN {
        if (t !~ /^[+]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][+-]?[0-9]+)?$/) exit 2;
        n = t + 0;
        if (!(n > 0 && n <= 120)) exit 2;
        printf "%.6f", n + m;
    }'
}

# JSON 正文里若显式给了 timeout，就以它为任务时限；否则用该命令的默认值。
budget_of() {
    default=$2
    case "${1:-}" in
        *'"timeout"'*)
            v=$(python3 -c 'import json,sys,math
try:
    t = float(json.loads(sys.argv[1]).get("timeout"))
except (ValueError, TypeError, AttributeError):
    t = None
print(t if t is not None and math.isfinite(t) and 0 < t <= 120 else "")' "$1") || v=
            [ -n "$v" ] && { echo "$v"; return; }
            ;;
    esac
    echo "$default"
}

# 读类命令专用：连不上（退出码 7）就先拉起桥再试一次。
# 绝不用于 js/click/fill —— 那些会改页面状态，重试等于又做一次。
retry_ro() {
    out=$("$@" 2>/dev/null); rc=$?      # 第一次失败的连接错误不必打扰用户，反正要重试
    if [ "$rc" -eq 7 ]; then
        sh "$D/bridge/restart.sh" >/dev/null 2>&1
        sleep 1.5
        out=$("$@"); rc=$?
    fi
    printf '%s' "$out"
    return "$rc"
}

post() {
    # post <任务时限> <端点> <正文>
    xb_http_wait=$(net_wait "$1") || usage
    request -m "$xb_http_wait" -H 'Content-Type: application/json' --data-binary "$3" "$B/api/$2"
}

[ "$#" -gt 0 ] || usage
command=$1
shift
case "$command" in
    status)
        case "${1:-}" in
            -v|--verbose) out=$(retry_ro request -m 10 "$B/status"); emit status --verbose "$out" $? ;;
            '') out=$(retry_ro request -m 10 "$B/status"); emit status "$out" $? ;;
            *) usage ;;
        esac ;;
    js)
        [ "$#" -ge 1 ] || usage
        limit=${2:-15}
        xb_http_wait=$(net_wait "$limit") || usage
        out=$(printf '%s' "$1" | request -m "$xb_http_wait" -H "X-Minis-Timeout: $limit" --data-binary @- "$B/api/raw"); emit js "$out" $? ;;
    text)
        all=; body='{}'
        if [ "${1:-}" = all ]; then all=--all; shift; fi
        if [ -n "${1:-}" ]; then body=$(json_args selector "$1") || exit 1; fi
        out=$(retry_ro post "$(budget_of "$body" 15)" text "$body"); emit "text $all" "$out" $? ;;
    snapshot)
        raw=; flags=; body=; limit=70
        for a in "$@"; do
            case "$a" in
                --raw) raw=1 ;;
                --all) limit=200 ;;
                --sel|--text) flags="$flags $a" ;;
                -*) usage ;;
                *) body=$a; raw=1 ;;
            esac
        done
        [ -n "$body" ] || body=$(json_args limit "$limit")
        out=$(retry_ro post "$(budget_of "$body" 20)" snapshot "$body"); rc=$?
        if [ -n "$raw" ]; then printf '%s\n' "$out"; else printf '%s\n' "$out" | fmt snapshot $flags; fi
        [ "$rc" -eq 0 ] || exit "$rc" ;;
    open)
        fresh=
        if [ "${1:-}" = --new ]; then fresh=1; shift; fi
        [ "$#" -ge 1 ] || usage
        url=$1
        # --new：任务确实需要并排/保留旧页状态（表单、滚动位置、登录流程做到一半）时才用
        if [ -n "$fresh" ]; then
            android-open "$url" >/dev/null 2>&1 && echo "新开标签: $url"
            exit 0
        fi
        # 有标签就导航它，绝不新开（android-open 每次都新开一个，几十次就几十个标签）
        xb status -v >/dev/null 2>&1 || { echo "桥没起：sh $D/bridge/restart.sh" >&2; exit 1; }
        note="原来没有标签，已新开"
        if xb status -v | python3 -c 'import json,sys; sys.exit(0 if json.load(sys.stdin).get("tabs") else 1)' 2>/dev/null; then
            code=$(python3 -c 'import json,sys; print("(()=>{location.href=%s;return 1})()" % json.dumps(sys.argv[1]))' "$url") || exit 1
            xb js "$code" >/dev/null 2>&1 && { echo "已在现有标签打开: $url"; exit 0; }
            note="有标签但没响应（浏览器不在前台），只能新开"
        fi
        android-open "$url" >/dev/null 2>&1 && echo "新开标签: $url（$note）" ;;
    click)
        [ "$#" -ge 1 ] || usage
        sel=$1
        # 快照里打印的是去掉 minis-ref: 前缀的短 ref，这里补回去；真选择器不受影响
        case "$sel" in *[!0-9a-zA-Z:-]*) ;; *-*-*:*) sel="minis-ref:$sel" ;; esac
        body=$(json_args selector "$sel") || exit 1
        out=$(post "$(budget_of "$body" 12)" click "$body"); emit click "$out" $? ;;
    fill)
        [ "$#" -ge 2 ] || usage
        body=$(json_args selector "$1" value "$2") || exit 1
        out=$(post "$(budget_of "$body" 12)" fill "$body"); emit fill "$out" $? ;;
    *) usage ;;
esac
