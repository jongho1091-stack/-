import discord
from discord import app_commands
from discord.ext import commands
import re
import os
import asyncio
from datetime import datetime, timedelta
from flask import Flask
from threading import Thread

# --- Render 가동용 웹 서버 ---
app = Flask('')
@app.route('/')
def home(): return "Bot is alive!"
def run(): app.run(host='0.0.0.0', port=8080)
def keep_alive(): Thread(target=run).start()

# --- 1. 레이드 모집 뷰 ---
class RaidView(discord.ui.View):
    def __init__(self, title, time, limit, end_dt, author):
        super().__init__(timeout=None)
        self.title, self.time, self.limit = title, time, limit
        self.author = author
        self.end_time = end_dt
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
        
        leave_btn = discord.ui.Button(label="취소 (get off)", style=discord.ButtonStyle.gray, custom_id="leave")
        leave_btn.callback = self.leave_callback
        self.add_item(leave_btn)

    def get_embed(self, closed=False):
        curr = sum(len(self.roster[r]) for r in self.roles)
        color = 0x5865F2 if not closed else 0x99AAB5
        now = datetime.utcnow() + timedelta(hours=9)
        display_time = self.end_time.strftime('%m/%d %H:%M') if self.end_time.date() > now.date() else self.end_time.strftime('%H:%M')
        desc = (f"**👤 모집자: {self.author.display_name}**\n━━━━━━━━━━━━━━━━━━━━\n"
                f"📅 **출발 시간:** {self.time}\n👥 **정원:** {self.limit}명 (현재 {curr}명)\n⏰ **모집 마감:** {display_time} 까지")
        embed = discord.Embed(title=f"⚔️ {self.title}{' (모집 종료)' if closed else ''}", description=desc, color=color)
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
            try: await self.author.send(f"🔔 **[{self.title}]** {name}님이 {role}로 참여했습니다.")
            except: pass
        await interaction.response.edit_message(embed=self.get_embed())
        if sum(len(self.roster[r]) for r in self.roles) >= self.limit: await self.close_raid(interaction.message)

    async def leave_callback(self, interaction: discord.Interaction):
        name = interaction.user.display_name
        for r in self.roster:
            if name in self.roster[r]: self.roster[r].remove(name)
        if interaction.user.id in self.participants: self.participants.remove(interaction.user.id)
        await interaction.response.edit_message(embed=self.get_embed())

    async def close_raid(self, message):
        if self.is_closed: return
        self.is_closed = True
        for item in self.children: item.disabled = True
        try:
            await message.edit(embed=self.get_embed(closed=True), view=self)
            mentions = " ".join([f"<@{u}>" for u in self.participants])
            if mentions: await message.reply(f"{mentions}\n🏁 **'{self.title}' 모집이 종료되었습니다!**")
        except: pass

# --- 2. 모달 및 모집 설정 로직 ---
class RecruitModal(discord.ui.Modal, title='📝 레기온 레이드 모집'):
    title_in = discord.ui.TextInput(label='제목', placeholder='(ex: 뿔암 / 정복 / 일반)')
    time_in = discord.ui.TextInput(label='출발 시간', placeholder='(ex: 26년 3월 13일 21시)')
    limit_in = discord.ui.TextInput(label='인원', placeholder='숫자만 입력 (ex: 6)')
    dur_in = discord.ui.TextInput(label='모집 마감 시간', placeholder='ex: 2026-02-07-21:00')

    def __init__(self, role=None, setup_interaction=None):
        super().__init__()
        self.role = role
        self.setup_interaction = setup_interaction

    async def on_submit(self, interaction: discord.Interaction):
        # 1. 꼬리표 방지용 defer (ephemeral로 짧게 처리)
        await interaction.response.defer(ephemeral=True)

        # 2. 날짜 계산
        now = datetime.utcnow() + timedelta(hours=9)
        val = self.dur_in.value.strip()
        target_dt = None
        nums = re.findall(r'\d+', val)
        if len(nums) >= 4:
            try:
                year = int(nums[0]); year = year + 2000 if year < 100 else year
                month, day, hour = int(nums[1]), int(nums[2]), int(nums[3])
                minute = int(nums[4]) if len(nums) >= 5 else 0
                target_dt = datetime(year, month, day, hour, minute)
            except: pass
        elif ':' in val or '-' in val or len(nums) == 2:
            try:
                h, m = map(int, nums[:2])
                target_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
                if target_dt < now: target_dt += timedelta(days=1)
            except: pass
        if not target_dt:
            try: target_dt = now + timedelta(minutes=int(re.sub(r'[^0-9]', '', val)))
            except: target_dt = now + timedelta(minutes=30)
            
        l_str = re.sub(r'[^0-9]', '', self.limit_in.value)
        limit = int(l_str) if l_str else 6
        
        # 3. 독립 메시지 전송 (channel.send 사용)
        user_mention = interaction.user.mention
        role_mention = self.role.mention if self.role else ""
        complete_msg = f"✅ {user_mention}께서 모집 작성을 완료하였습니다.\n{role_mention} 🌲 **모집 시작!**"
        
        view = RaidView(self.title_in.value, self.time_in.value, limit, target_dt, interaction.user)
        # 중요: followup 대신 channel.send를 써서 답장 관계를 끊습니다.
        sent_msg = await interaction.channel.send(content=complete_msg, embed=view.get_embed(), view=view)
        
        # 4. 이제 설정창을 지웁니다.
        if self.setup_interaction:
            try: await self.setup_interaction.delete_original_response()
            except: pass

        async def timer():
            wait = (target_dt - (datetime.utcnow() + timedelta(hours=9))).total_seconds()
            await asyncio.sleep(max(0, wait)); await view.close_raid(sent_msg)
        asyncio.create_task(timer())

class RoleSelectView(discord.ui.View):
    def __init__(self): super().__init__(timeout=60)
    
    @discord.ui.select(cls=discord.ui.RoleSelect, placeholder="📣 알림 보낼 역할을 선택하세요")
    async def select_role(self, interaction: discord.Interaction, select: discord.ui.Select):
        await interaction.response.send_modal(RecruitModal(select.values[0], setup_interaction=interaction))
        
    @discord.ui.button(label="알림 없이 작성하기", style=discord.ButtonStyle.gray)
    async def no_mention(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RecruitModal(None, setup_interaction=interaction))

class MyBot(commands.Bot):
    def __init__(self): super().__init__(command_prefix="!", intents=discord.Intents.all())
    async def setup_hook(self): await self.tree.sync()

bot = MyBot()

@bot.tree.command(name="모집", description="레이드 모집글을 작성합니다.")
async def recruit(interaction: discord.Interaction):
    # 모두가 볼 수 있게 설정 (ephemeral=False)
    await interaction.response.send_message("모집 설정을 시작합니다.", view=RoleSelectView(), ephemeral=False)

keep_alive()
bot.run(os.getenv('TOKEN'))
