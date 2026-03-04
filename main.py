import discord
from discord import app_commands
from discord.ext import commands
import re, os, asyncio, json
from datetime import datetime, timedelta, UTC
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
    return {"auto_role": None, "job_roles": {}, "setup_msg_id": None, "setup_chan_id": None, "ticket_settings": {}}

# --- [역할 부여] 관련 기능 (주신 코드 방식) ---
class NicknameModal(discord.ui.Modal, title='📝 별명 입력'):
    name_input = discord.ui.TextInput(label='사용하실 별명을 입력해주세요', placeholder='(예: 토끼공듀)', min_length=1, max_length=20)
    def __init__(self, emoji, role_name, job_roles):
        super().__init__()
        self.emoji, self.role_name, self.job_roles = emoji, role_name, job_roles

    async def on_submit(self, interaction: discord.Interaction):
        guild, member = interaction.guild, interaction.user
        user_input = self.name_input.value.strip()
        all_job_names = list(self.job_roles.values())
        to_remove = [r for r in member.roles if r.name in all_job_names]
        if to_remove:
            try: await member.remove_roles(*to_remove)
            except: pass
        new_role = discord.utils.get(guild.roles, name=self.role_name)
        if not new_role: return await interaction.response.send_message(f"❌ '{self.role_name}' 역할을 찾을 수 없습니다.", ephemeral=True)
        await member.add_roles(new_role)
        new_nick = f"{self.emoji}{user_input}"
        try:
            await member.edit(nick=new_nick[:32])
            await interaction.response.send_message(f"✅ **{self.role_name}** 설정 완료! 별명이 **{new_nick}**(으)로 변경되었습니다.", ephemeral=True)
        except:
            await interaction.response.send_message(f"✅ 역할 부여 완료! (별명은 수동 변경 바랍니다.)", ephemeral=True)

class DynamicJobView(discord.ui.View):
    def __init__(self, job_roles):
        super().__init__(timeout=None)
        self.job_roles = job_roles
        for emoji, role_name in self.job_roles.items():
            btn = discord.ui.Button(emoji=emoji, custom_id=f"role_{emoji}", style=discord.ButtonStyle.gray)
            btn.callback = self.make_cb(emoji, role_name)
            self.add_item(btn)
    def make_cb(self, emoji, role_name):
        async def cb(interaction): await interaction.response.send_modal(NicknameModal(emoji, role_name, self.job_roles))
        return cb

class SetupEditModal(discord.ui.Modal, title='📝 설정판 문구 수정'):
    content_input = discord.ui.TextInput(label='수정할 내용을 입력해주세요', style=discord.TextStyle.paragraph, min_length=1, max_length=1000)
    def __init__(self, bot): super().__init__(); self.bot = bot
    async def on_submit(self, interaction: discord.Interaction):
        c_id, m_id = self.bot.db.get("setup_chan_id"), self.bot.db.get("setup_msg_id")
        try:
            chan = self.bot.get_channel(c_id) or await self.bot.fetch_channel(c_id)
            msg = await chan.fetch_message(m_id)
            await msg.edit(content=self.content_input.value)
            await interaction.response.send_message("✅ 수정 완료!", ephemeral=True)
        except: await interaction.response.send_message("❌ 메시지 못 찾음.", ephemeral=True)

# --- [모집] 관련 기능 (요청하신 가이드라인 수정) ---
class RaidView(discord.ui.View):
    def __init__(self, title, time, limit, end_dt, author):
        super().__init__(timeout=None)
        self.title, self.time, self.limit, self.end_time, self.author = title, time, limit, end_dt, author
        self.roster, self.participants, self.is_closed = {}, set(), False
    @discord.ui.button(label="참석/변경", style=discord.ButtonStyle.primary, emoji="⚔️")
    async def join(self, i, b):
        if len(self.roster) >= self.limit and i.user.id not in self.roster: return await i.response.send_message("❌ 정원 초과", ephemeral=True)
        modal = RecruitEntryModal(self); await i.response.send_modal(modal)
    @discord.ui.button(label="취소", style=discord.ButtonStyle.gray)
    async def leave(self, i, b):
        if i.user.id in self.roster:
            self.roster.pop(i.user.id); self.participants.remove(i.user.id)
            await i.response.edit_message(embed=self.get_embed())
        else: await i.response.send_message("참여 중 아님", ephemeral=True)
    @discord.ui.button(label="마감", style=discord.ButtonStyle.danger)
    async def close_btn(self, i, b):
        if i.user.id != self.author.id: return
        await self.close_raid(i.message)
    def get_embed(self, closed=False):
        curr = len(self.roster); color = 0x5865F2 if not closed else 0x99AAB5
        desc = f"**👤 모집자: {self.author.display_name}**\n📅 **출발:** {self.time}\n👥 **정원:** {self.limit}명 (현재 {curr}명)"
        embed = discord.Embed(title=f"⚔️ {self.title}{' (종료)' if closed else ''}", description=desc, color=color)
        list_val = "\n".join([f"> {idx+1}. {info}" for idx, info in enumerate(self.roster.values())]) if self.roster else "> 인원 없음"
        embed.add_field(name="👥 참여 명단", value=list_val, inline=False); return embed
    async def close_raid(self, message):
        self.is_closed = True; [setattr(item, 'disabled', True) for item in self.children]
        await message.edit(embed=self.get_embed(closed=True), view=self)

class RecruitEntryModal(discord.ui.Modal, title='⚔️ 참석 정보'):
    job = discord.ui.TextInput(label='직업', min_length=2, max_length=10)
    char = discord.ui.TextInput(label='캐릭터명', min_length=1, max_length=20)
    def __init__(self, rv): super().__init__(); self.rv = rv
    async def on_submit(self, i):
        self.rv.roster[i.user.id] = f"{self.job.value} / {self.char.value}"
        self.rv.participants.add(i.user.id)
        await i.response.edit_message(embed=self.rv.get_embed())

class RecruitModal(discord.ui.Modal, title='📝 레이드 모집'):
    title_in = discord.ui.TextInput(label='제목', placeholder='') # 가이드 제거
    time_in = discord.ui.TextInput(label='출발 시간', placeholder='') # 가이드 제거
    limit_in = discord.ui.TextInput(label='인원', placeholder='') # 가이드 제거
    dur_in = discord.ui.TextInput(label='모집 마감 시간', placeholder='2026-03-04-21:00 (반드시 이 양식으로 작성)')

    def __init__(self, role=None, setup_interaction=None):
        super().__init__(); self.role, self.setup_interaction = role, setup_interaction

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        now = datetime.now(UTC) + timedelta(hours=9); val = self.dur_in.value.strip(); target_dt = None; nums = re.findall(r'\d+', val)
        if len(nums) >= 4:
            try:
                y = int(nums[0]); y = y + 2000 if y < 100 else y
                target_dt = datetime(y, int(nums[1]), int(nums[2]), int(nums[3]), int(nums[4]) if len(nums) >= 5 else 0, tzinfo=UTC) - timedelta(hours=9)
            except: pass
        if not target_dt: target_dt = datetime.now(UTC) + timedelta(minutes=30)
        limit = int(re.sub(r'[^0-9]', '', self.limit_in.value)) if re.sub(r'[^0-9]', '', self.limit_in.value) else 6
        view = RaidView(self.title_in.value, self.time_in.value, limit, target_dt + timedelta(hours=9), interaction.user)
        await interaction.channel.send(content=f"{self.role.mention if self.role else ''} 🌲 **모집 시작!**", embed=view.get_embed(), view=view)
        if self.setup_interaction: await self.setup_interaction.delete_original_response()

# --- [티켓] 기능 (유지) ---
async def archive_and_delete(channel, log_ch_id):
    history = [f"[{m.created_at.strftime('%m-%d %H:%M')}] {m.author.display_name}: {m.content}" async for m in channel.history(limit=None, oldest_first=True)]
    log_ch = channel.guild.get_channel(log_ch_id)
    if log_ch:
        with open("log.txt", "w", encoding="utf-8") as f: f.write("\n".join(history))
        await log_ch.send(f"📂 **기록: {channel.name}**", file=discord.File("log.txt")); os.remove("log.txt")
    await asyncio.sleep(3); await channel.delete()

class TicketView(discord.ui.View):
    def __init__(self, admin_role_id, category_name, log_ch_id):
        super().__init__(timeout=None)
        self.admin_role_id, self.category_name, self.log_ch_id = admin_role_id, category_name, log_ch_id
    @discord.ui.button(label="문의/신고", style=discord.ButtonStyle.success, custom_id="ticket_btn_final")
    async def open_ticket(self, i, b):
        guild, member = i.guild, i.user
        category = discord.utils.get(guild.categories, name=self.category_name) or await guild.create_category(self.category_name)
        over = {guild.default_role: discord.PermissionOverwrite(read_messages=False), member: discord.PermissionOverwrite(read_messages=True, send_messages=True)}
        ch = await guild.create_text_channel(name=f"문의-{member.display_name}", category=category, overwrites=over)
        emb = discord.Embed(title="📩 접수", description=f"{member.mention}님 내용을 남겨주세요.\n(3분 무응답 시 get off)", color=0x2f3136)
        emb.set_footer(text=f"로그채널ID: {self.log_ch_id}"); await ch.send(embed=emb)
        await i.response.send_message(f"✅ 생성: {ch.mention}", ephemeral=True)
        def check(m): return m.channel == ch and not m.author.bot
        try: await bot.wait_for('message', check=check, timeout=180.0)
        except asyncio.TimeoutError: await archive_and_delete(ch, self.log_ch_id)

# --- 메인 봇 ---
class MyBot(commands.Bot):
    def __init__(self): super().__init__(command_prefix="!", intents=discord.Intents.all()); self.db = load_db()
    async def setup_hook(self):
        if self.db.get("setup_msg_id"): self.add_view(DynamicJobView(self.db["job_roles"]))
        await self.tree.sync()
    async def on_member_join(self, m):
        r_id = self.db.get("auto_role")
        if r_id:
            role = m.guild.get_role(r_id)
            if role: await m.add_roles(role)

bot = MyBot()

@bot.tree.command(name="모집")
async def recruit(i):
    class RoleSelect(discord.ui.View):
        @discord.ui.select(cls=discord.ui.RoleSelect)
        async def s(self, i, s): await i.response.send_modal(RecruitModal(role=s.values[0], setup_interaction=i))
    await i.response.send_message("설정...", view=RoleSelect(), ephemeral=True)

@bot.tree.command(name="직업설정판_생성")
async def create_setup(i, 채널: discord.TextChannel, 내용: str):
    msg = await 채널.send(content=내용)
    bot.db["setup_msg_id"], bot.db["setup_chan_id"] = msg.id, 채널.id
    bot.db["job_roles"] = {}; save_db(bot.db); await i.response.send_message("✅ 생성 완료", ephemeral=True)

@bot.tree.command(name="직업역할_추가")
async def add_job(i, 이모지: str, 역할: discord.Role):
    bot.db["job_roles"][이모지] = 역할.name; save_db(bot.db)
    chan = bot.get_channel(bot.db["setup_chan_id"])
    msg = await chan.fetch_message(bot.db["setup_msg_id"])
    await msg.edit(view=DynamicJobView(bot.db["job_roles"]))
    await i.response.send_message(f"✅ 추가 완료: {이모지}", ephemeral=True)

@bot.tree.command(name="직업설정판_수정")
async def edit_setup(i): await i.response.send_modal(SetupEditModal(bot))

@bot.tree.command(name="입장역할설정")
async def set_auto(i, 역할: discord.Role):
    bot.db["auto_role"] = 역할.id; save_db(bot.db); await i.response.send_message("✅ 설정됨", ephemeral=True)

@bot.tree.command(name="티켓설정")
async def ticket_setup(i, 관리자역할: discord.Role, 상담카테고리명: str, 로그채널명: str):
    log_ch = await i.guild.create_text_channel(name=로그채널명)
    bot.db["ticket_settings"] = {"admin_role_id": 관리자역할.id, "category_name": 상담카테고리명, "log_ch_id": log_ch.id}
    save_db(bot.db); view = TicketView(관리자역할.id, 상담카테고리명, log_ch.id)
    await i.channel.send(content="📢 문의/신고 접수", view=view)
    await i.response.send_message("✅ 완료", ephemeral=True)

@bot.tree.command(name="상담종료")
async def close_ticket(i):
    async for m in i.channel.history(oldest_first=True, limit=1):
        if m.embeds:
            log_id = int(m.embeds[0].footer.text.split(": ")[1])
            await archive_and_delete(i.channel, log_id)

keep_alive()
bot.run(os.getenv('TOKEN'))
