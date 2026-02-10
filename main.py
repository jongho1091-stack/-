import discord
from discord import app_commands
from discord.ext import commands
import re
import os
import asyncio
import json
from datetime import datetime, timedelta
from flask import Flask
from threading import Thread

# --- Render 가동용 웹 서버 ---
app = Flask('')
@app.route('/')
def home(): return "Bot is alive!"
def run(): app.run(host='0.0.0.0', port=8080)
def keep_alive(): Thread(target=run).start()

# --- 데이터 저장 시스템 ---
DB_FILE = "guild_settings.json"
def save_db(data):
    with open(DB_FILE, 'w', encoding='utf-8') as f: json.dump(data, f, ensure_ascii=False, indent=4)
def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, 'r', encoding='utf-8') as f: return json.load(f)
    return {"auto_role": None, "job_roles": {}, "setup_msg_id": None, "setup_chan_id": None}

# --- 1. 별명 입력 팝업창 (Modal) ---
class NicknameModal(discord.ui.Modal, title='📝 별명 입력'):
    name_input = discord.ui.TextInput(
        label='사용하실 별명을 입력해주세요',
        placeholder='(예: 토끼공듀)',
        min_length=1,
        max_length=20
    )

    def __init__(self, emoji, role_name, job_roles):
        super().__init__()
        self.emoji, self.role_name, self.job_roles = emoji, role_name, job_roles

    async def on_submit(self, interaction: discord.Interaction):
        guild, member = interaction.guild, interaction.user
        user_input = self.name_input.value.strip()

        all_job_names = list(self.job_roles.values())
        to_remove = [r for r in member.roles if r.name in all_job_names]
        if to_remove: await member.remove_roles(*to_remove)

        new_role = discord.utils.get(guild.roles, name=self.role_name)
        if not new_role:
            return await interaction.response.send_message(f"❌ '{self.role_name}' 역할을 찾을 수 없습니다.", ephemeral=True)
        await member.add_roles(new_role)

        new_nick = f"{self.emoji}{user_input}"
        try:
            await member.edit(nick=new_nick[:32])
            await interaction.response.send_message(f"✅ **{self.role_name}** 설정 완료! 별명이 **{new_nick}**(으)로 변경되었습니다.", ephemeral=True)
        except:
            await interaction.response.send_message(f"✅ 역할 부여 완료! (봇 권한 문제로 별명은 수동 변경 바랍니다.)", ephemeral=True)

# --- 2. 직업 선택 버튼 뷰 ---
class DynamicJobView(discord.ui.View):
    def __init__(self, job_roles):
        super().__init__(timeout=None)
        self.job_roles = job_roles
        for emoji, role_name in self.job_roles.items():
            btn = discord.ui.Button(emoji=emoji, custom_id=f"role_{emoji}", style=discord.ButtonStyle.gray)
            btn.callback = self.role_callback
            self.add_item(btn)

    async def role_callback(self, interaction: discord.Interaction):
        emoji = interaction.data['custom_id'].replace("role_", "")
        role_name = self.job_roles.get(emoji)
        await interaction.response.send_modal(NicknameModal(emoji, role_name, self.job_roles))

# --- 3. 레이드 모집 시스템 ---
class RaidView(discord.ui.View):
    def __init__(self, title, time, limit, end_dt, author):
        super().__init__(timeout=None)
        self.title, self.time, self.limit = title, time, limit
        self.author, self.end_time = author, end_dt
        self.roles = ["수호성", "검성", "살성", "궁성", "마도성", "정령성", "치유성", "호법성"]
        self.role_icons = {"수호성": "🛡️", "검성": "🗡️", "살성": "⚔️", "궁성": "🏹", "마도성": "🔥", "정령성": "✨", "치유성": "❤️", "호법성": "🪄"}
        self.roster = {role: [] for role in self.roles}
        self.participants, self.is_closed = set(), False
        self.create_buttons()

    def create_buttons(self):
        styles = {"수호성": 1, "검성": 1, "살성": 3, "궁성": 3, "마도성": 4, "정령성": 4, "치유성": 2, "호법성": 2}
        for role in self.roles:
            btn = discord.ui.Button(label=role, style=discord.ButtonStyle(styles[role]), emoji=self.role_icons[role], custom_id=role)
            btn.callback = self.button_callback
            self.add_item(btn)
        
        leave_btn = discord.ui.Button(label="참여 취소", style=discord.ButtonStyle.gray, custom_id="leave")
        leave_btn.callback = self.leave_callback
        self.add_item(leave_btn)

        close_btn = discord.ui.Button(label="모집 마감 / 작성자 전용", style=discord.ButtonStyle.danger, emoji="🛑", custom_id="force_close")
        close_btn.callback = self.force_close_callback
        self.add_item(close_btn)

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
        party_list = []
        for r in self.roles:
            for p_name in self.roster[r]: party_list.append(f"**{p_name}** ({r})")
        list_val = "\n".join([f"> {idx+1}. {p}" for idx, p in enumerate(party_list)]) if party_list else "> 현재 참여 인원 없음"
        embed.add_field(name="👥 현재 참여 명단 (실시간)", value=list_val, inline=False)
        return embed

    async def button_callback(self, interaction: discord.Interaction):
        if self.is_closed: return
        role, name, uid = interaction.data['custom_id'], interaction.user.display_name, interaction.user.id
        for r in self.roster:
            if name in self.roster[r]: self.roster[r].remove(name)
        if sum(len(self.roster[r]) for r in self.roles) < self.limit:
            self.roster[role].append(name); self.participants.add(uid)
            try:
                alert = await interaction.channel.send(f"🔔 {self.author.mention}님, **{name}** 참여 ({role})")
                await alert.delete()
            except: pass
        await interaction.response.edit_message(embed=self.get_embed())
        if sum(len(self.roster[r]) for r in self.roles) >= self.limit: await self.close_raid(interaction.message)

    async def leave_callback(self, interaction: discord.Interaction):
        name = interaction.user.display_name; removed = False
        for r in self.roster:
            if name in self.roster[r]: self.roster[r].remove(name); removed = True
        if interaction.user.id in self.participants: self.participants.remove(interaction.user.id)
        if removed:
            try:
                alert = await interaction.channel.send(f"⚪ {self.author.mention}님, **{name}** 참여 취소 (get off)")
                await alert.delete()
            except: pass
        await interaction.response.edit_message(embed=self.get_embed())

    async def force_close_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.author.id: return await interaction.response.send_message("❌ 작성자만 마감할 수 있습니다!", ephemeral=True)
        await interaction.response.defer(ephemeral=True); await self.close_raid(interaction.message)

    async def close_raid(self, message):
        if self.is_closed: return
        self.is_closed = True
        for item in self.children: item.disabled = True
        try:
            await message.edit(embed=self.get_embed(closed=True), view=self)
            mentions = " ".join([f"<@{u}>" for u in self.participants])
            if mentions: await message.reply(f"{mentions}\n🏁 **'{self.title}' 모집이 종료되었습니다!**")
        except: pass

# --- 4. 티켓 시스템 ---
class TicketView(discord.ui.View):
    def __init__(self, admin_role_id, category_name, log_channel_id):
        super().__init__(timeout=None)
        self.admin_role_id, self.category_name, self.log_channel_id = admin_role_id, category_name, log_channel_id

    async def create_ticket(self, interaction, type_label):
        guild, user = interaction.guild, interaction.user
        admin_role, category = guild.get_role(self.admin_role_id), discord.utils.get(guild.categories, name=self.category_name)
        if not category: category = await guild.create_category(self.category_name, overwrites={guild.default_role: discord.PermissionOverwrite(read_messages=False), admin_role: discord.PermissionOverwrite(read_messages=True)})
        overwrites = {guild.default_role: discord.PermissionOverwrite(read_messages=False), user: discord.PermissionOverwrite(read_messages=True, send_messages=True), admin_role: discord.PermissionOverwrite(read_messages=True, send_messages=True)}
        channel = await guild.create_text_channel(name=f"{type_label}-{user.display_name}", category=category, overwrites=overwrites)
        embed = discord.Embed(title=f"🎫 레기온 {type_label} 접수", description=f"안녕하세요 {user.mention}님!\n운영진이 확인 중입니다.\n\n💡 상담 종료: `/상담종료`", color=0x3498db)
        embed.set_footer(text=f"ID: {self.log_channel_id}"); await channel.send(content=f"{user.mention} | {admin_role.mention}", embed=embed)
        await interaction.response.defer(ephemeral=True)
        try: await interaction.client.wait_for('message', check=lambda m: m.channel == channel and m.author.id == user.id, timeout=180.0)
        except asyncio.TimeoutError: await channel.delete(reason="응답 없음")

    @discord.ui.button(label="📝 문의 / 건의", style=discord.ButtonStyle.success, custom_id="suggest")
    async def suggest(self, interaction, button): await self.create_ticket(interaction, "문의-건의")
    @discord.ui.button(label="🚨 신고하기", style=discord.ButtonStyle.danger, custom_id="report")
    async def report(self, interaction, button): await self.create_ticket(interaction, "신고")

# --- 5. 모집 작성 유틸 ---
class RoleSelectView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.select(cls=discord.ui.RoleSelect, placeholder="📣 알림 보낼 역할을 선택하세요")
    async def select_role(self, interaction, select): await interaction.response.send_modal(RecruitModal(role=select.values[0], setup_interaction=interaction))
    @discord.ui.button(label="알림 없이 작성하기", style=discord.ButtonStyle.gray)
    async def no_mention(self, interaction, button): await interaction.response.send_modal(RecruitModal(role=None, setup_interaction=interaction))

class RecruitModal(discord.ui.Modal, title='📝 레기온 레이드 모집'):
    title_in = discord.ui.TextInput(label='제목', placeholder='(ex: 뿔암 / 정복 / 일반)')
    time_in = discord.ui.TextInput(label='출발 시간', placeholder='(ex: 26년 3월 13일 21시)')
    limit_in = discord.ui.TextInput(label='인원', placeholder='숫자만 입력 (ex: 6)')
    dur_in = discord.ui.TextInput(label='모집 마감 시간 (24시간제)', placeholder='ex: 2026-02-07-21:00')

    def __init__(self, role=None, setup_interaction=None):
        super().__init__(); self.role, self.setup_interaction = role, setup_interaction

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        complete_msg = f"✅ {interaction.user.mention}께서 모집 작성을 완료하였습니다.\n\n{self.role.mention if self.role else ''} 🌲 **모집 시작!**"
        now = datetime.utcnow() + timedelta(hours=9); val = self.dur_in.value.strip(); target_dt = None; nums = re.findall(r'\d+', val)
        if len(nums) >= 4:
            try:
                y = int(nums[0]); y = y + 2000 if y < 100 else y
                target_dt = datetime(y, int(nums[1]), int(nums[2]), int(nums[3]), int(nums[4]) if len(nums) >= 5 else 0)
            except: pass
        if not target_dt: target_dt = now + timedelta(minutes=30)
        limit = int(re.sub(r'[^0-9]', '', self.limit_in.value)) if re.sub(r'[^0-9]', '', self.limit_in.value) else 6
        view = RaidView(self.title_in.value, self.time_in.value, limit, target_dt, interaction.user)
        sent_msg = await interaction.channel.send(content=complete_msg, embed=view.get_embed(), view=view)
        if self.setup_interaction:
            try: await self.setup_interaction.delete_original_response()
            except: pass
        async def timer():
            await asyncio.sleep(max(0, (target_dt - (datetime.utcnow() + timedelta(hours=9))).total_seconds())); await view.close_raid(sent_msg)
        asyncio.create_task(timer())

# --- 6. 봇 메인 및 관리자 명령어 ---
class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=discord.Intents.all()); self.db = load_db()
    async def setup_hook(self):
        if self.db["job_roles"]: self.add_view(DynamicJobView(self.db["job_roles"]))
        await self.tree.sync()
    async def on_member_join(self, member):
        if self.db["auto_role"]:
            role = member.guild.get_role(self.db["auto_role"])
            if role: await member.add_roles(role)

bot = MyBot()

@bot.tree.command(name="모집", description="레이드 모집글을 작성합니다.")
async def recruit(interaction): await interaction.response.send_message("모집 설정을 시작합니다.", view=RoleSelectView(), ephemeral=True)

@bot.tree.command(name="입장역할설정", description="신규 멤버 자동 부여 역할을 지정합니다.")
@app_commands.checks.has_permissions(administrator=True)
async def set_auto_role(interaction, 역할: discord.Role):
    bot.db["auto_role"] = 역할.id; save_db(bot.db)
    await interaction.response.send_message(f"✅ 자동 입장 역할: **{역할.name}**", ephemeral=True)

@bot.tree.command(name="직업설정판_생성", description="설정판 안내 메시지를 생성합니다.")
@app_commands.checks.has_permissions(administrator=True)
async def create_setup_msg(interaction, 채널: discord.TextChannel, 내용: str):
    bot.db["job_roles"] = {}; sent_msg = await 채널.send(content=내용)
    bot.db["setup_msg_id"], bot.db["setup_chan_id"] = sent_msg.id, 채널.id
    save_db(bot.db); await interaction.response.send_message("✅ 생성 완료!", ephemeral=True)

@bot.tree.command(name="직업역할_추가", description="이모지와 역할을 연결합니다.")
@app_commands.checks.has_permissions(administrator=True)
async def add_job_role(interaction, 이모지: str, 역할: discord.Role):
    if not bot.db["setup_msg_id"]: return await interaction.response.send_message("❌ 먼저 설정판을 생성해주세요.", ephemeral=True)
    bot.db["job_roles"][이모지] = 역할.name; save_db(bot.db); await update_setup_message(interaction.guild)
    await interaction.response.send_message(f"✅ 추가: {이모지} -> {역할.name}", ephemeral=True)

@bot.tree.command(name="직업역할_삭제", description="특정 버튼을 삭제합니다.")
@app_commands.checks.has_permissions(administrator=True)
async def remove_job_role(interaction, 이모지: str):
    if 이모지 in bot.db["job_roles"]:
        del bot.db["job_roles"][이모지]; save_db(bot.db); await update_setup_message(interaction.guild)
        await interaction.response.send_message(f"✅ 삭제: {이모지}", ephemeral=True)
    else: await interaction.response.send_message("❌ 등록되지 않은 이모지입니다.", ephemeral=True)

async def update_setup_message(guild):
    c_id, m_id = bot.db.get("setup_chan_id"), bot.db.get("setup_msg_id")
    if c_id and m_id:
        try: await (await guild.get_channel(c_id).fetch_message(m_id)).edit(view=DynamicJobView(bot.db["job_roles"]))
        except: pass

@bot.tree.command(name="티켓설정", description="티켓 시스템 설정")
@app_commands.checks.has_permissions(administrator=True)
async def ticket_setup(interaction, 관리자역할: discord.Role, 상담카테고리명: str, 로그채널명: str):
    log_ch = await interaction.guild.create_text_channel(name=로그채널명, overwrites={interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False), 관리자역할: discord.PermissionOverwrite(read_messages=True)})
    await interaction.channel.send(embed=discord.Embed(title="📢 레기온 문의 / 건의 및 신고 접수", description="아래 버튼을 눌러 티켓을 생성하세요.", color=0x2f3136), view=TicketView(관리자역할.id, 상담카테고리명, log_ch.id))
    await interaction.response.send_message("✅ 티켓 설정 완료!", ephemeral=True)

@bot.tree.command(name="상담종료", description="상담 종료 및 로그 저장")
async def close_ticket(interaction):
    if "-" not in interaction.channel.name: return await interaction.response.send_message("❌ 상담 채널이 아닙니다.", ephemeral=True)
    await interaction.response.defer(ephemeral=True); log_ch = None
    async for msg in interaction.channel.history(oldest_first=True, limit=1):
        if msg.embeds: log_ch = interaction.guild.get_channel(int(msg.embeds[0].footer.text.split(": ")[1]))
    history = [f"[{m.created_at.strftime('%m-%d %H:%M')}] {m.author.display_name}: {m.content}" async for m in interaction.channel.history(limit=None, oldest_first=True)]
    with open("log.txt", "w", encoding="utf-8") as f: f.write("\n".join(history))
    if log_ch: await log_ch.send(f"📂 **종료 기록: {interaction.channel.name}**", file=discord.File("log.txt"))
    if os.path.exists("log.txt"): os.remove("log.txt")
    await asyncio.sleep(3); await interaction.channel.delete()

keep_alive()
bot.run(os.getenv('TOKEN'))
