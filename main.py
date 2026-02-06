import discord
from discord import app_commands
from discord.ext import commands
import re
import os
import asyncio
from datetime import datetime, timedelta
from flask import Flask
from threading import Thread

# --- Render 24시간 가동을 위한 웹 서버 설정 ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

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
        
        # [2025-08-22] Character change 시 "get off" 사용
        leave_btn = discord.ui.Button(label="취소 (get off)", style=discord.ButtonStyle.gray, custom_id="leave")
        leave_btn.callback = self.leave_callback
        self.add_item(leave_btn)

    def get_embed(self, closed=False):
        curr = sum(len(self.roster[r]) for r in self.roles)
        color = 0x5865F2 if not closed else 0x99AAB5
        now = datetime.utcnow() + timedelta(hours=9)
        
        display_time = self.end_time.strftime('%H:%M')
        if self.end_time.date() > now.date():
            display_time = self.end_time.strftime('%m/%d %H:%M')

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

# --- 2. 레기온 티켓 기능 (건의/신고) ---
class TicketView(discord.ui.View):
    def __init__(self, admin_role_id, category_name, log_channel_id):
        super().__init__(timeout=None)
        self.admin_role_id = admin_role_id
        self.category_name = category_name
        self.log_channel_id = log_channel_id

    async def create_ticket(self, interaction, type_label):
        guild = interaction.guild
        user = interaction.user
        admin_role = guild.get_role(self.admin_role_id)
        
        category = discord.utils.get(guild.categories, name=self.category_name)
        if not category:
            overwrites = {guild.default_role: discord.PermissionOverwrite(read_messages=False), admin_role: discord.PermissionOverwrite(read_messages=True)}
            category = await guild.create_category(self.category_name, overwrites=overwrites)

        ticket_overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            admin_role: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        channel = await guild.create_text_channel(name=f"{type_label}-{user.display_name}", category=category, overwrites=ticket_overwrites)

        embed = discord.Embed(title=f"🎫 레기온 {type_label} 접수", 
                              description=f"안녕하세요 {user.mention}님!\n현재 **레기온 운영진**이 내용을 확인하고 있습니다.\n내용을 남겨주시면 곧 답변드리겠습니다.\n\n💡 상담이 끝나면 운영진이 `/상담종료` 명령어로 마무리합니다.", color=0x3498db)
        embed.set_footer(text=f"ID: {self.log_channel_id}")
        await channel.send(content=f"{user.mention} | {admin_role.mention}", embed=embed)
        await interaction.response.send_message(f"✅ {type_label} 채널이 생성되었습니다: {channel.mention}", ephemeral=True)

    @discord.ui.button(label="📝 건의하기", style=discord.ButtonStyle.primary, custom_id="suggest")
    async def suggest(self, interaction, button): await self.create_ticket(interaction, "건의")
    @discord.ui.button(label="🚨 신고하기", style=discord.ButtonStyle.danger, custom_id="report")
    async def report(self, interaction, button): await self.create_ticket(interaction, "신고")

# --- 3. 봇 클래스 및 명령어 ---
class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=discord.Intents.all())

    async def setup_hook(self):
        await self.tree.sync()

bot = MyBot()

@bot.tree.command(name="티켓설정", description="레기온 티켓 시스템을 설정합니다.")
@app_commands.checks.has_permissions(administrator=True)
async def ticket_setup(interaction: discord.Interaction, 관리자역할: discord.Role, 상담카테고리명: str, 로그채널명: str):
    guild = interaction.guild
    overwrites = {guild.default_role: discord.PermissionOverwrite(read_messages=False), 관리자역할: discord.PermissionOverwrite(read_messages=True)}
    log_ch = await guild.create_text_channel(name=로그채널명, overwrites=overwrites)
    
    view = TicketView(관리자역할.id, 상담카테고리명, log_ch.id)
    embed = discord.Embed(
        title="📢 레기온 건의 및 신고 접수", 
        description=(
            f"우리 **레기온**을 위한 소중한 의견을 들려주세요.\n"
            f"상담은 운영진과 본인만 볼 수 있는 비밀 채널에서 진행됩니다.\n\n"
            f"**📝 건의하기**: 운영 및 규칙 관련 의견\n"
            f"**🚨 신고하기**: 비매너 유저 및 규칙 위반 제보\n\n"
            f"⚠️ **주의사항**\n"
            f"**장난성 건의 및 신고는 제재 대상이 될 수 있습니다.**"
        ), 
        color=0x2f3136
    )
    await interaction.response.send_message(embed=embed, view=view)

@bot.tree.command(name="상담종료", description="상담 종료 후 로그 저장 및 채널 삭제")
async def close_ticket(interaction: discord.Interaction):
    if not isinstance(interaction.channel, discord.TextChannel) or "-" not in interaction.channel.name:
        return await interaction.response.send_message("❌ 상담 채널에서만 사용 가능합니다.", ephemeral=True)

    await interaction.response.send_message("💾 로그를 생성하고 채널을 닫는 중입니다...", ephemeral=True)
    
    log_ch = None
    async for msg in interaction.channel.history(oldest_first=True, limit=1):
        if msg.embeds and msg.embeds[0].footer.text:
            try: log_ch = interaction.guild.get_channel(int(msg.embeds[0].footer.text.split(": ")[1]))
            except: pass
    
    history = []
    async for message in interaction.channel.history(limit=None, oldest_first=True):
        history.append(f"[{message.created_at.strftime('%Y-%m-%d %H:%M')}] {message.author.display_name}: {message.content}")
    
    log_content = "\n".join(history)
    file_path = f"log_{interaction.channel.name}.txt"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(log_content)
    
    if log_ch:
        await log_ch.send(f"📂 **상담 종료 기록: {interaction.channel.name}**", file=discord.File(file_path))
    
    os.remove(file_path)
    await asyncio.sleep(3)
    await interaction.channel.delete()

# --- 레이드 모집 관련 (기존 로직) ---
class RecruitModal(discord.ui.Modal, title='📝 레기온 레이드 모집'):
    title_in = discord.ui.TextInput(label='제목', placeholder='(예시: 뿔암 / 정복 / 일반)')
    time_in = discord.ui.TextInput(label='출발 시간', placeholder='(예시: 23:00 출발)')
    limit_in = discord.ui.TextInput(label='인원', placeholder='숫자만 입력 (예: 6)')
    dur_in = discord.ui.TextInput(label='마감시간 (예: 21:00 / 1시간 뒤)')

    def __init__(self, role):
        super().__init__()
        self.role = role

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        now = datetime.utcnow() + timedelta(hours=9)
        target_dt = now + timedelta(minutes=30)
        l_str = re.sub(r'[^0-9]', '', self.limit_in.value); limit = int(l_str) if l_str else 6
        view = RaidView(self.title_in.value, self.time_in.value, limit, target_dt, interaction.user)
        ment = self.role.mention if self.role else ""
        sent_msg = await interaction.followup.send(content=f"{ment} 🌲 **모집 시작!**", embed=view.get_embed(), view=view)
        async def timer():
            await asyncio.sleep(max(0, (target_dt - now).total_seconds()))
            await view.close_raid(sent_msg)
        asyncio.create_task(timer())

class RoleSelectView(discord.ui.View):
    def __init__(self): super().__init__(timeout=60)
    @discord.ui.select(cls=discord.ui.RoleSelect, placeholder="📣 알림 보낼 역할을 선택하세요")
    async def select_role(self, interaction, select): await interaction.response.send_modal(RecruitModal(select.values[0]))

@bot.tree.command(name="모집", description="레이드 모집글을 작성합니다.")
async def recruit(interaction: discord.Interaction):
    await interaction.response.send_message("모집 설정을 시작합니다.", view=RoleSelectView(), ephemeral=True)

# 실행
keep_alive()
bot.run(os.getenv('TOKEN'))
