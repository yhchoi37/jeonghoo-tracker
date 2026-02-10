import os
import subprocess
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler
from telegram.request import HTTPXRequest

# --- 1. 환경 변수 로드 ---
load_dotenv()

# --- 2. 설정 가져오기 (변수명 변경됨) ---
TOKEN = os.getenv("TELEGRAM_TOKEN")
USER_ID_STR = os.getenv("TELEGRAM_USER_ID")
JH_TRACKER_DIR = os.getenv("JH_TRACKER_DIR", "/opt/jeonghoo-tracker")
IMMICH_DIR = os.getenv("IMMICH_DIR", "/opt/immich")

# 설정값 검증
if not TOKEN or not USER_ID_STR or not JH_TRACKER_DIR:
    print("❌ 오류: .env 파일에 설정값이 부족합니다!")
    exit(1)

MY_ID = int(USER_ID_STR)

# --- 명령어 실행 함수 (작업 폴더를 선택할 수 있게 개선) ---
def run_cmd(cmd, working_dir):
    try:
        # 지정된 폴더(working_dir)에서 명령어 실행
        result = subprocess.check_output(cmd, shell=True, cwd=working_dir, stderr=subprocess.STDOUT)
        return result.decode('utf-8')
    except subprocess.CalledProcessError as e:
        return f"❌ 에러 발생:\n{e.output.decode('utf-8')}"
    except FileNotFoundError:
        return f"❌ 오류: 폴더를 찾을 수 없습니다 -> {working_dir}"

# --- 메시지 보내기 도우미 ---
async def send_msg(update: Update, text: str):
    if update.callback_query:
        await update.callback_query.message.reply_text(text)
    else:
        await update.message.reply_text(text)

# --- 권한 체크 ---
def check_auth(update: Update):
    if update.effective_user.id != MY_ID:
        return False
    return True

# ==============================
# 🎮 메인 메뉴 (버튼)
# ==============================
async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_auth(update): return

    keyboard = [
        # 정후 트래커 관련
        [
            InlineKeyboardButton("🔍 [JH] 상태 확인", callback_data='jh_status'),
            InlineKeyboardButton("⬇️ [JH] 깃 풀 (Only)", callback_data='jh_git_pull')
        ],
        [
            InlineKeyboardButton("🚀 [JH] 시작", callback_data='jh_start'),
            InlineKeyboardButton("🛑 [JH] 중지", callback_data='jh_stop')
        ],
        [
            InlineKeyboardButton("🔄 [JH] 전체 업데이트 (Pull+Build)", callback_data='jh_full_update')
        ],
        # Immich 관련 (구분선 느낌으로 분리)
        [
            InlineKeyboardButton("🖼️ [Immich] 업데이트 (Pull+Up)", callback_data='immich_update')
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    msg = "🤖 **통합 관리자 봇**\n원하는 작업을 선택하세요:"
    if update.callback_query:
        await update.callback_query.message.reply_text(msg, reply_markup=reply_markup)
    else:
        await update.message.reply_text(msg, reply_markup=reply_markup)

# ==============================
# 🚦 버튼 핸들러 (분배기)
# ==============================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not check_auth(update):
        await query.message.reply_text("🚫 주인님이 아니시군요!")
        return

    # --- 정후 트래커 기능 ---
    if query.data == 'jh_status':
        await run_jh_cmd(update, "docker compose ps", "🔍 [JH] 상태 확인 중...")
    elif query.data == 'jh_git_pull':
        await run_jh_cmd(update, "git pull", "⬇️ [JH] 소스코드 가져오는 중...")
    elif query.data == 'jh_start':
        await run_jh_cmd(update, "docker compose up -d tracker", "🚀 [JH] 트래커 시작...")
    elif query.data == 'jh_stop':
        await run_jh_cmd(update, "docker compose stop tracker", "🛑 [JH] 트래커 정지...")
    elif query.data == 'jh_full_update':
        await jh_full_update_func(update)
    
    # --- Immich 기능 ---
    elif query.data == 'immich_update':
        await immich_update_func(update)

# ==============================
# 🛠️ 실제 동작 함수들
# ==============================

# [공통] 정후 트래커 명령어 실행용
async def run_jh_cmd(update, cmd, msg):
    await send_msg(update, msg)
    output = run_cmd(cmd, JH_TRACKER_DIR)
    await send_msg(update, f"결과:\n{output}")

# [JH] 전체 업데이트 (Git Pull + Rebuild)
async def jh_full_update_func(update):
    await send_msg(update, "🔄 [JH] 풀업데이트 시작...\n(Git Pull + Rebuild)")
    
    git_out = run_cmd("git pull", JH_TRACKER_DIR)
    docker_out = run_cmd("docker compose up -d --build tracker", JH_TRACKER_DIR)
    
    await send_msg(update, f"✅ [JH] 완료!\n\n[Git]\n{git_out}\n\n[Docker]\n{docker_out}")

# [Immich] 업데이트 (Pull + Up)
async def immich_update_func(update):
    if not IMMICH_DIR:
        await send_msg(update, "⚠️ .env 파일에 IMMICH_DIR 설정이 없습니다!")
        return

    await send_msg(update, "🖼️ [Immich] 이미지 최신화 및 재시작 중...\n(docker compose pull && up -d)")
    
    # 명령어 두 개를 한 번에 실행
    cmd = "docker compose pull && docker compose up -d"
    output = run_cmd(cmd, IMMICH_DIR)
    
    await send_msg(update, f"✅ [Immich] 업데이트 완료!\n\n{output}")

# ==============================
# 메인 실행부
# ==============================
if __name__ == '__main__':
    # [수정] 타임아웃 설정을 추가한 request 객체 생성
    t_request = HTTPXRequest(connection_pool_size=8, connect_timeout=60.0, read_timeout=60.0)

    # [수정] 빌더에 request 옵션 추가
    app = ApplicationBuilder().token(TOKEN).request(t_request).build()

    app.add_handler(CommandHandler("menu", show_menu))
    app.add_handler(CommandHandler("start", show_menu))
    app.add_handler(CallbackQueryHandler(button_handler))

    print("🤖 통합 관리 봇이 실행되었습니다!")
    app.run_polling()