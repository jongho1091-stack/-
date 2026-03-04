import discord
from discord import app_commands
from discord.ext import commands
import re, os, asyncio, json
from datetime import datetime, timedelta, UTC
from flask import Flask
from threading import Thread

# --- 서버 유지용 ---
app = Flask('')
@app.route('/')
def home(): return "Bot is alive!"
def run(): app.run(host='0.0.0.0', port=8080)
def keep_alive(): Thread(target=run).start()

# --- 데이터 저장 ---
DB_FILE = "guild_settings.json"
def save_db(data):
    with open(DB_FILE, 'w', encoding='utf-8') as f: json.dump(data, f, ensure_ascii=False, indent=4)
def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, 'r', encoding='utf-8') as f: return json.load(f)
        except: pass
    return {"auto_role": None, "job_roles": {}, "setup_msg_id": None, "setup_chan_id": None, "ticket_settings": {}}

# --- [공통] 티켓 로그 및 삭제 ---
async def archive_and_delete(channel, log_ch_id):
    history = []
    async for m in channel.history(limit=None, oldest_first=True):
        history.append(f"[{m.created_at.strftime('%m-%d %H:%M')}] {m.author.display_name}: {m.content}")
    log_ch = channel.guild.get_channel(log_ch_id)
    if log_ch:
        file_path = f"log_{channel.id}.txt"
        with open(file_path, "w", encoding="utf-8") as f: f.write("\n".join(history))
        await log_ch.send(f"📂 **상담 기록: {channel.name}**", file=discord.File(file_path))
        if os.path.exists(file_path): os.remove(file_path)
    await asyncio.sleep(3)
    try: await channel.delete()
    except: pass

# --- [역할 시스템] ---
class NicknameModal(discord.ui.Modal, title='📝 별명 입력'):
    name_input = discord.ui.TextInput(label='사용하실 별명을 입력해주세요', placeholder='(ex.토끼공듀)', min_length=1, max_length=20)
    def __init__(self, emoji, role_name, job_roles):
        super().__init__(); self.emoji, self.role_name, self.job_roles = emoji, role_name, job_roles
    async def on_submit(self, i: discord.Interaction):
        await i.response.defer(ephemeral=True)
        guild, member = i.guild, i.user
        all_job_names = list(self.job_roles.values())
        to_remove = [r for r in member.roles if r.name in all_job_names]
        if to_remove:
            try: await member.remove_roles(*to_remove)
            except: pass
        new_role = discord.utils.get(guild.roles, name=self.role_name)
        if new_role: await member.add_roles(new_role)
        new_nick = f"{self.emoji}{self.name_input.value.strip()}"
        try: await member.edit(nick=new_nick[:32])
        except: pass
        await i.followup.send(f"✅ **{self.role_name}** 설정 완료!", ephemeral=True)

class DynamicJobView(discord.ui.View):
    def __init__(self, job_roles):
        super().__init__(timeout=None)
        self.job_roles = job_roles
        for emoji, role_name in self.job_roles.items():
            btn = discord.ui.Button(emoji=emoji, custom_id=f"role_{emoji}", style=discord.ButtonStyle.gray)
            btn.callback = self.make_cb(emoji, role_name)
            self.add_item(btn)
    def make_cb(self, emoji, role_name):
        async def cb(i): await i.response.send_modal(NicknameModal(emoji, role_name, self.job_roles))
        return cb

# --- [모집 시스템] 서울 시간 기준 ---
class RaidView(discord.ui.View):
    def __init__(self, title, time, limit, end_dt, author):
        super().__init__(timeout=None)
        self.title, self.time, self.limit, self.end_time, self.author = title, time, limit, end_dt, author
        self.roster = {}; self.is_closed = False
    
    @discord.ui.button(label="참여/변경하기", style=discord.ButtonStyle.primary, emoji="⚔️")
    async def join(self, i, b):
        if not self.is_closed: await i.response.send_modal(RaidEntryModal(self))
        
    @discord.ui.button(label="참여 취소", style=discord.ButtonStyle.gray)
    async def leave(self, i, b):
        if i.user.id in self.roster:
            self.roster.pop(i.user.id); await i.response.edit_message(embed=self.get_embed())
            a = await i.channel.send(f"⚪ {i.user.display_name} 참여 취소 (get off)"); await a.delete(delay=3)
            
    @discord.ui.button(label="모집 마감", style=discord.ButtonStyle.danger, emoji="🛑")
    async def close_btn(self, i, b):
        if i.user.id == self.author.id: await self.close_raid(i.message)
        
    def get_embed(self, closed=False):
        curr = len(self.roster); color = 0x5865F2 if not closed else 0x99AAB5
        display_time = self.end_time.strftime('%m/%d %H:%M')
        desc = f"**👤 모집자: {self.author.display_name}**\n📅 **출발:** {self.time}\n👥 **정원:** {self.limit}명 (현재 {curr}명)\n⏰ **마감:** {display_time} 까지"
        embed = discord.Embed(title=f"⚔️ {self.title}{' (종료)' if closed else ''}", description=desc, color=color)
        list_val = "\n".join([f"> {idx+1}. {info}" for idx, info in enumerate(self.roster.values())]) if self.roster else "> 인원 없음"
        embed.add_field(name="👥 참여 명단", value=list_val, inline=False)
        return embed
        
    async def close_raid(self, message):
        self.is_closed = True; [setattr(item, 'disabled', True) for item in self.children]
        try: await message.edit(embed=self.get_embed(closed=True), view=self)
        except: pass

class RaidEntryModal(discord.ui.Modal, title='⚔️ 참석 정보'):
    job = discord.ui.TextInput(label='직업', placeholder='(줄임말 없이 작성)')
    char = discord.ui.TextInput(label='캐릭터명', placeholder='(ex.토끼공듀)')
    power = discord.ui.TextInput(label='전투력', placeholder='(ex.12+)')

    def __init__(self, rv): super().__init__(); self.rv = rv
    async def on_submit(self, i):
        self.rv.roster[i.user.id] = f"{self.job.value} / {self.char.value} / {self.power.value}"
        await i.response.edit_message(embed=self.rv.get_embed())
        notif = await i.channel.send(f"🔔 {self.rv.author.mention}님, **{i.user.display_name}**님이 참여! ({self.job.value}/{self.power.value})")
        await notif.delete(delay=3)

class RecruitModal(discord.ui.Modal, title='📝 레이드 모집'):
    t_in = discord.ui.TextInput(label='제목', placeholder='')
    tm_in = discord.ui.TextInput(label='출발 시간', placeholder='')
    l_in = discord.ui.TextInput(label='인원', placeholder='')
    d_in = discord.ui.TextInput(label='모집 마감 시간', placeholder='2026-03-04-21:00')
    def __init__(self, role=None, setup_i=None): super().__init__(); self.role, self.setup_i = role, setup_i
    async def on_submit(self, i):
        await i.response.defer(ephemeral=True)
        now_kst = datetime.now(UTC) + timedelta(hours=9)
        target_dt = None; nums = re.findall(r'\d+', self.d_in.value)
        if len(nums) >= 4:
            try:
                y = int(nums[0]); y = y + 2000 if y < 100 else y
                target_dt = datetime(y, int(nums[1]), int(nums[2]), int(nums[3]), int(nums[4]) if len(nums) >= 5 else 0)
            except: pass
        if not target_dt: target_dt = now_kst + timedelta(minutes=30)
        limit = int(re.sub(r'[^0-9]', '', self.l_in.value)) if re.sub(r'[^0-9]', '', self.l_in.value) else 6
        view = RaidView(self.t_in.value, self.tm_in.value, limit, target_dt, i.user)
        sent = await i.channel.send(content=f"{self.role.mention if self.role else ''} 🌲 **모집 시작!**", embed=view.get_embed(), view=view)
        if self.setup_i: await self.setup_i.delete_original_response()
        wait_seconds = (target_dt - now_kst).total_seconds()
        async def timer():
            await asyncio.sleep(max(0, wait_seconds)); await view.close_raid(sent)
        asyncio.create_task(timer())

# --- [티켓 시스템] ---
class TicketView(discord.ui.View):
    def __init__(self, admin_role_id, category_name, log_ch_id):
        super().__init__(timeout=None)
        self.admin_role_id, self.category_name, self.log_ch_id = admin_role_id, category_name, log_ch_id
    async def create_ticket(self, i, prefix):
        guild, member = i.guild, i.user
        category = discord.utils.get(guild.categories, name=self.category_name) or await guild.create_category(self.category_name)
        admin_role = guild.get_role(self.admin_role_id)
        over = {guild.default_role: discord.PermissionOverwrite(read_messages=False), member: discord.PermissionOverwrite(read_messages=True, send_messages=True), admin_role: discord.PermissionOverwrite(read_messages=True, send_messages=True)}
        ch = await guild.create_text_channel(name=f"{prefix}-{member.display_name}", category=category, overwrites=over)
        emb = discord.Embed(title=f"📩 {prefix} 접수", description=f"{member.mention}님, 내용을 남겨주세요.\n(3분 무응답 시 자동 종료/get off)", color=0x2f3136)
        emb.set_footer(text=f"로그채널ID: {self.log_ch_id}")
        await ch.send(embed=emb)
        await i.response.send_message(f"✅ {prefix} 채널 생성됨: {ch.mention}", ephemeral=True)
        def check(m): return m.channel == ch and not m.author.bot
        try: await bot.wait_for('message', check=check, timeout=180.0)
        except asyncio.TimeoutError: await archive_and_delete(ch, self.log_ch_id)
    @discord.ui.button(label="문의/건의하기", style=discord.ButtonStyle.success, custom_id="btn_inquiry")
    async def inquiry(self, i, b): await self.create_ticket(i, "문의")
    @discord.ui.button(label="신고하기", style=discord.ButtonStyle.danger, custom_id="btn_report")
    async def report(self, i, b): await self.create_ticket(i, "신고")

# --- 봇 메인 ---
class MyBot(commands.Bot):
    def __init__(self): super().__init__(command_prefix="!", intents=discord.Intents.all()); self.db = load_db()
    async def setup_hook(self):
        if self.db.get("setup_msg_id"): self.add_view(DynamicJobView(self.db["job_roles"]))
        if self.db.get("ticket_settings"):
            ts = self.db["ticket_settings"]
            self.add_view(TicketView(ts["admin_role_id"], ts["category_name"], ts["log_ch_id"]))
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
        @discord.ui.select(cls=discord.ui.RoleSelect, placeholder="📣 알림 역할 선택")
        async def s(self, i, s): await i.response.send_modal(RecruitModal(role=s.values[0], setup_i=i))
        @discord.ui.button(label="알림 없이", style=discord.ButtonStyle.gray)
        async def n(self, i, b): await i.response.send_modal(RecruitModal(role=None, setup_i=i))
    await i.response.send_message("모집 설정...", view=RoleSelect(), ephemeral=True)

@bot.tree.command(name="입장역할설정")
async def set_auto(i, 역할: discord.Role):
    bot.db["auto_role"] = 역할.id; save_db(bot.db); await i.response.send_message(f"✅ {역할.name} 설정됨", ephemeral=True)

@bot.tree.command(name="티켓설정")
async def ticket_setup(i, 관리자역할: discord.Role, 상담카테고리명: str, 로그채널명: str):
    log_ch = await i.guild.create_text_channel(name=로그채널명)
    bot.db["ticket_settings"] = {"admin_role_id": 관리자역할.id, "category_name": 상담카테고리명, "log_ch_id": log_ch.id}
    save_db(bot.db); await i.channel.send(embed=discord.Embed(title="📢 문의 및 신고"), view=TicketView(관리자역할.id, 상담카테고리명, log_ch.id))
    await i.response.send_message("✅ 티켓 설정 완료", ephemeral=True)

@bot.tree.command(name="상담종료")
async def close_ticket(i):
    if "문의-" in i.channel.name or "신고-" in i.channel.name:
        log_id = None
        async for m in i.channel.history(oldest_first=True, limit=1):
            if m.embeds and m.embeds[0].footer: log_id = int(m.embeds[0].footer.text.split(": ")[1])
        await i.response.send_message("🏁 종료 중..."); await archive_and_delete(i.channel, log_id)

@bot.tree.command(name="직업설정판_생성")
async def create_setup(i, 채널: discord.TextChannel, 내용: str):
    msg = await 채널.send(content=내용); bot.db["setup_msg_id"], bot.db["setup_chan_id"] = msg.id, 채널.id
    bot.db["job_roles"] = {}; save_db(bot.db); await i.response.send_message("✅ 생성 완료", ephemeral=True)

@bot.tree.command(name="직업설정판_문구수정")
async def edit_setup_text(i, 수정할내용: str):
    if not bot.db.get("setup_msg_id"): return await i.response.send_message("❌ 설정판 없음", ephemeral=True)
    try:
        chan = bot.get_channel(bot.db["setup_chan_id"]); msg = await chan.fetch_message(bot.db["setup_msg_id"])
        await msg.edit(content=수정할내용, view=DynamicJobView(bot.db["job_roles"]))
        await i.response.send_message("✅ 문구 수정 완료", ephemeral=True)
    except: await i.response.send_message("❌ 수정 실패", ephemeral=True)

@bot.tree.command(name="직업역할_추가")
async def add_job(i, 이모지: str, 역할: discord.Role):
    bot.db["job_roles"][이모지] = 역할.name; save_db(bot.db)
    chan = bot.get_channel(bot.db["setup_chan_id"]); msg = await chan.fetch_message(bot.db["setup_msg_id"])
    await msg.edit(view=DynamicJobView(bot.db["job_roles"])); await i.response.send_message(f"✅ {역할.name} 추가됨", ephemeral=True)

keep_alive()
bot.run(os.getenv('TOKEN'))
