# (이전 코드의 상단 import 및 클래스들은 동일하게 유지)

# --- [역할 시스템: 문구 수정용 팝업창] ---
class EditSetupModal(discord.ui.Modal, title='📝 설정판 문구 수정'):
    # 대화창처럼 길게 입력할 수 있는 필드 (기존 내용이 있으면 미리 채워짐)
    content_input = discord.ui.TextInput(
        label='수정할 내용을 입력하세요 (마크다운 가능)',
        style=discord.TextStyle.paragraph, # 여러 줄 입력 가능
        placeholder='**우리 길드 직업 설정**\n\n아래 버튼을 눌러 직업을 선택해주세요!',
        required=True,
        max_length=1000
    )

    def __init__(self, msg, job_roles):
        super().__init__()
        self.msg = msg
        self.job_roles = job_roles
        self.content_input.default = msg.content # 기존 문구를 창에 미리 띄워줌

    async def on_submit(self, i: discord.Interaction):
        # 입력한 내용으로 메시지 업데이트
        await self.msg.edit(content=self.content_input.value, view=DynamicJobView(self.job_roles))
        await i.response.send_message("✅ 설정판 문구가 성공적으로 수정되었습니다!", ephemeral=True)

# --- 봇 메인 내 명령어 수정 ---

@bot.tree.command(name="직업설정판_문구수정")
async def edit_setup_text(i: discord.Interaction):
    if not bot.db.get("setup_msg_id"):
        return await i.response.send_message("❌ 먼저 생성된 설정판이 있어야 합니다.", ephemeral=True)
    
    try:
        chan = bot.get_channel(bot.db["setup_chan_id"])
        msg = await chan.fetch_message(bot.db["setup_msg_id"])
        
        # 팝업창(Modal) 띄우기
        await i.response.send_modal(EditSetupModal(msg, bot.db["job_roles"]))
    except Exception as e:
        await i.response.send_message(f"❌ 수정 창을 열 수 없습니다: {e}", ephemeral=True)

# (나머지 명령어 및 bot.run 부분은 이전과 동일)
