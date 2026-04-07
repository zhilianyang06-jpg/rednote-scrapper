#!/usr/bin/env zsh
# 小红书采集器管理脚本
# 用法: xhs start | stop | status | restart

PYTHON="/opt/anaconda3/bin/python3.12"
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
APP="$APP_DIR/app.py"
PID_FILE="$APP_DIR/.xhs.pid"
LOG_FILE="$APP_DIR/.xhs.log"
CLEAR_FLAG="$APP_DIR/.xhs.clear"
PORT=5001
URL="http://localhost:$PORT"

_pid() {
  [[ -f "$PID_FILE" ]] && cat "$PID_FILE" || echo ""
}

_running() {
  local pid=$(_pid)
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

_port_in_use() {
  lsof -ti tcp:$PORT &>/dev/null
}

_kill_port() {
  local pids
  pids=$(lsof -ti tcp:$PORT 2>/dev/null)
  [[ -n "$pids" ]] && echo "$pids" | xargs kill -9 2>/dev/null
}

cmd_start() {
  if _running; then
    echo "✅ 采集器已在运行 (PID $(_pid))  →  $URL"
    open "$URL" 2>/dev/null
    return
  fi

  # 端口被其他进程占用时先清理
  if _port_in_use; then
    echo "⚠️  端口 $PORT 被占用，正在释放..."
    _kill_port
    sleep 0.8
  fi

  echo "🚀 启动小红书采集器..."
  nohup "$PYTHON" "$APP" >> "$LOG_FILE" 2>&1 &
  echo $! > "$PID_FILE"

  # 等待端口就绪（最多 8 秒）
  local i=0
  while (( i < 16 )); do
    sleep 0.5
    _port_in_use && break
    (( i++ ))
  done

  if _port_in_use && _running; then
    # 新一轮：自动清空上一次的数据
    if [[ -f "$CLEAR_FLAG" ]]; then
      curl -s -X POST "$URL/clear" > /dev/null
      rm -f "$CLEAR_FLAG"
      echo "🗑️  已清空上次记录，开始新一轮采集"
    fi
    echo "✅ 启动成功 (PID $(_pid))  →  $URL"
    open "$URL" 2>/dev/null
  else
    echo "❌ 启动失败，最近日志："
    tail -20 "$LOG_FILE"
    rm -f "$PID_FILE"
  fi
}

cmd_stop() {
  # 询问是否导出
  if _port_in_use; then
    echo -n "📥 关闭前是否导出本轮数据？[Y/n] "
    read -r answer
    if [[ "$answer" != "n" && "$answer" != "N" ]]; then
      local filename="xhs_notes_$(date +%Y%m%d_%H%M%S).xlsx"
      local save_path="$HOME/Desktop/$filename"
      curl -s "$URL/export" -o "$save_path"
      if [[ -f "$save_path" ]]; then
        echo "✅ 已导出到桌面：$filename"
      else
        echo "⚠️  导出失败，文件可在 $APP_DIR/data/xhs_notes.xlsx 手动取用"
      fi
    else
      echo "⏭️  跳过导出"
    fi
  fi

  # 设置下次启动时清空的标记
  touch "$CLEAR_FLAG"

  local pid=$(_pid)
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null
    sleep 0.5
    kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null
    echo "🛑 采集器已停止 (PID $pid)"
  else
    echo "⚪ 采集器未在运行"
  fi
  # 确保端口彻底释放
  _port_in_use && _kill_port
  rm -f "$PID_FILE"
}

cmd_status() {
  if _running; then
    echo "✅ 运行中 (PID $(_pid))  →  $URL"
  else
    echo "⚪ 未运行"
    rm -f "$PID_FILE"
  fi
}

cmd_restart() {
  cmd_stop
  sleep 0.5
  cmd_start
}

case "${1:-start}" in
  start)   cmd_start ;;
  stop)    cmd_stop ;;
  status)  cmd_status ;;
  restart) cmd_restart ;;
  *)
    echo "用法: xhs [start|stop|status|restart]"
    echo "  start   — 启动并在浏览器中打开（默认）"
    echo "  stop    — 停止服务"
    echo "  status  — 查看运行状态"
    echo "  restart — 重启服务"
    ;;
esac
