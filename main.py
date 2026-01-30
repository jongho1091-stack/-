import discord
from discord import app_commands
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
        self.author = author
        # 한국 시각 계산 (UTC+9)
        self.end_time = datetime.utcnow() + timedelta(hours=9) + timedelta(minutes=duration_min)
        self.roles = ["수호성", "검성", "살성", "궁성", "마도성", "정령성", "치유성", "호법성"]
        self.role_icons = {"수호성": "🛡️", "검성": "🗡️", "살성": "⚔️", "궁성": "🏹", "마도성": "🔥", "정령성": "✨", "치유성": "❤️", "호법성": "🪄"}
        self.roster = {role: [] for role in self.roles}
        self.participants = set()
        self.is_closed = False
        self.create_buttons()

    def create_buttons(self):
        styles = {"수호성": 1, "검성": 1, "살성": 3, "궁성": 3, "마도성": 4, "정령성": 4, "치유성": 2, "호법성": 2}
        for role in self.roles:
            btn = discord.ui.Button(label=role, style=discord.ButtonStyle(styles[role]), emoji=self.role_icons[role], custom_id=role)
            btn.callback = self.button_callback
            self.add_item(btn)
        
        # "get off" 규칙 반영
        leave_btn = discord.ui.Button(label="취소 (get off)", style=discord.ButtonStyle.gray, custom_id="leave")
        leave_btn.callback = self.leave_callback
        self.add_item(leave_btn)

    def get_embed(self, closed=False):
        curr = sum(len(self.roster[r]) for r in self.roles)
        color = 0x5865F2 if not closed else 0x99AAB5
        display_time = self.end_time.strftime('%H:%M')
        
        embed = discord.Embed(
            title=f"⚔️ {self.title}{' (모집 종료)' if closed else ''}", 
            description=f"📅 **출발 시간:** {self.time}\n👥 **정원:** {self.limit}명 (현재 {curr}명)\n⏰ **모집 마감시간:** {display_time} 까지", 
            color=color
        )
        embed.set_author(name=f"모집자: {self.author.display_name}", icon_url=self.author.display_avatar.url)
        
        for i in range(0, 8, 4):
            val = "".join([f"{self.role_icons[r]} **{r}**: {', '.join(self.roster[r]) if self.roster[r] else '대기 중'}\n" for r in self.roles[i:i+4]])
            embed.add_field(name="\u200b", value=val, inline=True)
        return embed

    async def button_callback(self, interaction: discord.Interaction):
        if self.is_closed: return
        role, name, uid = interaction.data['custom_id'], interaction.user.display_name, interaction.user.id
        for r in self.roster:
            if name in self.roster[r]: self.roster[r].remove(name)
        if sum(len(self.roster[r]) for r in self.roles) < self.limit:
            self.roster[role].append(name)
            self.participants.add(uid)
            try: await self.author.send(f"🔔 **[{self.title}]** {name}님 참여!")
            except: pass
        await interaction.response.edit_message(embed=self.get_embed())
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
        try:
            await message.edit(embed=self.get_embed(closed=True), view=self)
            mentions = " ".join([f"<@{u}>" for u in self.participants])
            if mentions: await message.reply(f"{mentions}\n🏁 모집이 종료되었습니다!")
        except: pass

# --- 2. 입력 모달 ---
class RecruitModal(discord.ui.Modal, title='📝 레이드 모집 작성'):
    title_in = discord.ui.TextInput(label='제목', placeholder='(예시: 뿔암 / 정복 / 일반 / 부캐팟)')
    time_in = discord.ui.TextInput(label='출발 시간', placeholder='(예시: 23:00 출발)')
    limit_in = discord.ui.TextInput(label='인원', placeholder='(숫자만 적어주세요.)')
    # 길드장님이 요청하신 예시 문구 반영
    dur_in = discord.ui.TextInput(
        label='모집 마감시간 설정', 
        placeholder='(예시: 30분 or 1시간 30분 or 3시간)',
        default="30분"
    )

    def __init__(self, role):
        super().__init__()
        self.role = role

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            # 인원 숫자 추출
            l_str = re.sub(r'[^0-9]', '', self.limit_in.value)
            limit = int(l_str) if l_str else 6
            
            # --- 시간 자동 분석 로직 ---
            raw_dur = self.dur_in.value.replace(" ", "")
            final_minutes = 0
            
            if "시간" in raw_dur:
                # '시간' 앞의 숫자와 '분' 앞의 숫자를 각각 추출
                hours = re.findall(r'(\d+(?:\.\d+)?)시간', raw_dur)
                minutes = re.findall(r'(\d+)분', raw_dur)
                
                if hours: final_minutes += int(float(hours[0]) * 60)
                if minutes: final_minutes += int(minutes[0])
                # 숫자만 띡 적었는데 '시간'이 포함된 경우 (예: 2시간) 처리
                if not hours and not minutes:
                    only_num = re.sub(r'[^0-9.]', '', raw_dur)
                    final_minutes = int(float(only_num) * 60) if only_num else 60
            else:
                # '시간'이라는 단어가 없으면 전체를 '분'으로 간주
                num_only = re.sub(r'[^0-9]', '', raw_dur)
                final_minutes = int(num_only) if num_only else 30

            view = RaidView(self.title_in.value, self.time_in.value, limit, final_minutes, interaction.user)
            ment = self.role.mention if self.role else ""
            sent_msg = await interaction.followup.send(content=f"{ment} 🌲 **레이드 모집이 시작되었습니다!**", embed=view.get_embed(), view=view)
            
            async def timer():
                await asyncio.sleep(final_minutes * 60)
                await view.close_raid(sent_msg)
            asyncio.create_task(timer())
            
        except Exception as e:
            await interaction.followup.send(f"🚨 입력 형식이 잘못되었습니다: {e}", ephemeral=True)

# --- 3. 봇 실행 ---
class MyBot(commands.Bot):
    def __init__(self): super().__init__(command_prefix="!", intents=discord.Intents.all())
    async def setup_hook(self): await self.tree.sync()

bot = MyBot()

@bot.tree.command(name="모집", description="레이드 모집글을 작성합니다.")
@app_commands.describe(알람_역할="알림을 보낼 역할(태그)을 선택하세요 (생략 가능).")
async def recruit(interaction: discord.Interaction, 알람_역할: discord.Role = None):
    # 이제 마감 시간을 미리 고를 필요 없이 바로 모달을 띄웁니다.
    await interaction.response.send_modal(RecruitModal(알람_역할))

bot.run(os.getenv('TOKEN'))
