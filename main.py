import discord
from discord.ext import commands
import re
import os
import asyncio
from datetime import datetime, timedelta

# --- 1. 레이드 모집 현황 뷰 (RaidView) ---
class RaidView(discord.ui.View):
    def __init__(self, title, time, limit, duration_min, author):
        super().__init__(timeout=None)
        self.title, self.time, self.limit = title, time, limit
        self.duration_min = duration_min
        self.author = author
        # 한국 시간 기준(UTC+9) 마감시간 계산
        self.end_time = datetime.utcnow() + timedelta(hours=9) + timedelta(minutes=duration_min)
        self.roles = ["수호성", "검성", "살성", "궁성", "마도성", "정령성", "치유성", "호법성"]
        self.role_icons = {"수호성": "🛡️", "검성": "🗡️", "살성": "⚔️", "궁성": "🏹", "마도성": "🔥", "정령성": "✨", "치유성": "❤️", "호법성": "🪄"}
        self.roster = {role: [] for role in self.roles}
        self.participants = set()
        self.is_closed = False
        self.create_buttons()

    def create_buttons(self):
        # 직업별 버튼 색상 설정
        styles = {"수호성": 1, "검성": 1, "살성": 3, "궁성": 3, "마도성": 4, "정령성": 4, "치유성": 2, "호법성": 2}
        for role in self.roles:
            btn = discord.ui.Button(label=role, style=discord.ButtonStyle(styles[role]), emoji=self.role_icons[role], custom_id=role)
            btn.callback = self.button_callback
            self.add_item(btn)
        
        # "get off" 규칙 반영 버튼
        leave_btn = discord.ui.Button(label="취소 (get off)", style=discord.ButtonStyle.gray, custom_id="leave")
        leave_btn.callback = self.leave_callback
        self.add_item(leave_btn)

    def get_embed(self, closed=False):
        curr = sum(len(self.roster[r]) for r in self.roles)
        color = 0x5865F2 if not closed else 0x99AAB5
        display_time = self.end_time.strftime('%H:%M')
        
        # 띄어쓰기 수정: 모집 마감시간
        embed = discord.Embed(
            title=f"⚔️ {self.title}{' (모집 종료)' if closed else ''}", 
            description=f"📅 **일시:** {self.time}\n👥 **정원:** {self.limit}명 (현재 {curr}명)\n⏰ **모집 마감시간:** {display_time} 까지", 
            color=color
        )
        # 작성자 정보 표시
        embed.set_author(name=f"모집자: {self.author.display_name}", icon_url=self.author.display_avatar.url)
        
        # 역할별 명단 가로 정렬
        for i in range(0, 8, 4):
            val = "".join([f"{self.role_icons[r]} **{r}**: {', '.join(self.roster[r]) if self.roster[r] else '대기 중'}\n" for r in self.roles[i:i+4]])
            embed.add_field(name="\u200b", value=val, inline=True)
            
        if closed:
            embed.set_footer(text="이 모집은 종료되었습니다.")
        return embed

    async def button_callback(self, interaction: discord.Interaction):
        if self.is_closed: return
        role, name, uid = interaction.data['custom_id'], interaction.user.display_name, interaction.user.id
        
        # 중복 참여 방지 및 역할 변경 처리
        for r in self.roster:
            if name in self.roster[r]: self.roster[r].remove(name)
            
        if sum(len(self.roster[r]) for r in self.roles) < self.limit:
            self.roster[role].append(name)
            self.participants.add(uid)
            # 작성자에게 실시간 DM 알림
            try: await self.author.send(f"🔔 **[{self.title}]** `{name}`님이 `{role}`로 참여했습니다.")
            except: pass
        
        await interaction.response.edit_message(embed=self.get_embed())
        
        # 정원 충족 시 즉시 마감
        if sum(len(self.roster[r]) for r in self.roles) >= self.limit:
            await self.close_raid(interaction.message)

    async def leave_callback(self, interaction: discord.Interaction):
        name = interaction.user.display_name
        for r in self.roster:
            if name in self.roster[r]: self.roster[r].remove(name)
        await interaction.response.edit_message(embed=self.get_embed())

    async def close_raid(self, message):
        if self.is_closed: return
        self.is_closed = True
        for item in self.children: item.disabled = True
        
        await message.edit(embed=self.get_embed(closed=True), view=self)
        
        # 참여자 전원 멘션 알림
        mentions = " ".join([f"<@{u}>" for u in self.participants])
        if mentions:
            await message.reply(f"{mentions}\n🏁 **'{self.title}' 모집이 종료되었습니다!**")

# --- 2. 입력 모달 및 역할 선택 뷰 ---
class RecruitModal(discord.ui.Modal, title='📝 레이드 모집 작성'):
    # 요청하신 예시 문구 반영
    title_in = discord.ui.TextInput(label='제목', placeholder='(예시: 뿔암 / 정복 / 일반 / 부캐팟)')
    time_in = discord.ui.TextInput(label='출발 시간', placeholder='(예시: 23:00 출발)')
    limit_in = discord.ui.TextInput(label='인원', placeholder='(숫자만 적어주세요.)')
    dur_in = discord.ui.TextInput(label='마감(분)', placeholder='(숫자만 적어주세요. 분 단위 입니다.)', default="30")

    def __init__(self, role, msg):
        super().__init__()
        self.role, self.msg = role, msg

    async def on_submit(self, interaction: discord.Interaction):
        try:
            if self.msg: await self.msg.delete()
            # 숫자만 추출
            limit = int(re.sub(r'[^0-9]', '', self.limit_in.value))
            dur = int(re.sub(r'[^0-9]', '', self.dur_in.value))
            
            view = RaidView(self.title_in.value, self.time_in.value, limit, dur, interaction.user)
            ment = self.role.mention if self.role else ""
            
            await interaction.response.send_message(content=f"{ment} 🌲 **레이드 모집이 시작되었습니다!**", embed=view.get_embed(), view=view)
            
            # 타이머 작동 (시간 초과 시 자동 마감)
            msg = await interaction.original_response()
            await asyncio.sleep(dur * 60)
            await view.close_raid(msg)
        except: pass

class RoleSelectView(discord.ui.View):
    def __init__(self): super().__init__(timeout=60)
    
    @discord.ui.select(cls=discord.ui.RoleSelect, placeholder="알림 보낼 역할 선택 (선택 사항)")
    async def select_role(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        role = select.values[0] if select.values else None
        await interaction.response.send_modal(RecruitModal(role, interaction.message))

    @discord.ui.button(label="알림 없이 바로 작성", style=discord.ButtonStyle.gray)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RecruitModal(None, interaction.message))

# --- 3. 봇 실행 및 명령어 ---
class MyBot(commands.Bot):
    def __init__(self): super().__init__(command_prefix="!", intents=discord.Intents.all())
    async def setup_hook(self): await self.tree.sync()

bot = MyBot()

@bot.tree.command(name="모집", description="레이드 모집글을 작성합니다.")
async def recruit(interaction: discord.Interaction):
    await interaction.response.send_message("알림을 보낼 역할이 있나요? (없으면 바로 작성을 누르세요)", view=RoleSelectView(), ephemeral=True)

bot.run(os.getenv('TOKEN'))
