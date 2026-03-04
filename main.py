import discord
from discord import app_commands
from discord.ext import commands
import re, os, asyncio, json
from datetime import datetime, timedelta, UTC
from flask import Flask
from threading import Thread

# --- 웹 서버 (24시간 유지용) ---
app = Flask('')
@app.route('/')
def home(): return "Bot is alive!"
def run():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
def keep_alive(): Thread(target=run).start()

# --- DB 설정 (서버별 독립 구조) ---
DB_FILE = "guild_settings.json"
def save_db(data):
    with open(DB_FILE, 'w', encoding='utf-8') as f: json.dump(data, f, ensure_ascii=False, indent=4)
def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, 'r', encoding='utf-8') as f: return json.load(f)
    return {}

# --- [역할] 별명 입력 Modal ---
class NicknameModal(discord.ui.Modal, title='📝 별명 입력'):
    name_input = discord.ui.TextInput(label='사용하실 별명을 입력해주세요', placeholder='(예: 토끼공듀)', min_length=1, max_length=20)
    def __init__(self, emoji, role_name, job_roles):
        super().__init__(); self.emoji, self.role_name, self.job_roles = emoji, role_name, job_roles
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild, member = interaction.guild, interaction.user
        all_job_names = list(self.job_roles.values())
        to_remove = [r for r in member.roles if r.name in all_job_names]
        if to_remove:
            try: await member.remove_roles(*to_remove)
            except: pass
        new_role = discord.utils.get(guild.roles, name=self.role_name)
        if new_role: 
            try: await member.add_roles(new_role)
            except: pass
        try: await member.edit(nick=f"{self.emoji}{self.name_input.value.strip()}"[:32])
        except: pass
        await interaction.followup.send(f"✅ **{self.role_name}** 설정 완료!", ephemeral=True)

class RoleAssignView(discord.ui.View):
    def __init__(self, bot, guild_id):
        super().__init__(timeout=None)
        self.bot = bot
        guild_data = self.bot.db.get(str(guild_id), {"job_roles": {}})
        for emoji, role_name in guild_data["job_roles"].items():
            btn = discord.ui.Button(label=role_name, emoji=emoji, style=discord.ButtonStyle.secondary, custom_id=f"role_{guild_id}_{role_name}")
            btn.callback = self.make_cb(emoji, role_name, guild_data["job_roles"])
            self.add_item(btn)
    def make_cb(self, emoji, role_name, job_roles):
        async def cb(i): await i.response.send_modal(NicknameModal(emoji, role_name, job_roles))
        return cb

# --- [티켓] 뷰 ---
class TicketView(discord.ui.View):
    def __init__(self, admin_role_id, category_name, log_ch_id):
        super().__init__(timeout=None)
        self.admin_role_id, self.category_name, self.log_ch_id = admin_role_id, category_name, log_ch_id
    @discord.ui.button(label="문의하기", style=discord.ButtonStyle.success, emoji="🙋", custom_id="open_ticket_btn_v3")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        category = discord.utils.get(guild.categories, name=self.category_name)
        if not category: category = await guild.create_category(self.category_name)
        admin_role = guild.get_role(self.admin_role_id)
        over = {guild.default_role: discord.PermissionOverwrite(read_messages=False), interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True), admin_role: discord.PermissionOverwrite(read_messages=True, send_messages=True)}
        ticket_ch = await guild.create_text_channel(name=f"문의-{interaction.user.display_name}", category=category, overwrites=over)
        embed = discord.Embed(title="📩 문의 접수", description=f"{interaction.user.mention}님, 문의 내용을 남겨주세요.", color=0x2f3136)
        embed.set_footer(text=f"로그채널ID: {self.log_ch_id}")
        await ticket_ch.send(embed=embed)
        await interaction.response.send_message(f"✅ 티켓 생성됨!", ephemeral=True)

# --- [레이드 모집] 기능 ---
class RaidEntryModal(discord.ui.Modal, title='⚔️ 레이드 참석 정보 입력'):
    job = discord.ui.TextInput(label='직업', placeholder='(줄임말 없이 작성)', min_length=2, max_length=10)
    char_name = discord.ui.TextInput(label='캐릭터명', placeholder='(ex.토끼공듀)', min_length=1, max_length=20)
    power = discord.ui.TextInput(label='전투력', placeholder='(ex.12+)', min_length=1, max_length=10)
    def __init__(self, raid_view): super().__init__(); self.raid_view = raid_view
    async def on_submit(self, interaction: discord.Interaction):
        if self.raid_view.is_closed: return await interaction.response.send_message("❌ 이미 마감됨", ephemeral=True)
        self.raid_view.roster[interaction.user.id] = f"{self.job.value} / {self.char_name.value} / {self.power.value}"
        self.raid_view.participants.add(interaction.user.id)
        await interaction.response.edit_message(embed=self.raid_view.get_embed())

class RaidView(discord.ui.View):
    def __init__(self, title, time, limit, author, close_time):
        super().__init__(timeout=None)
        self.title, self.time, self.limit, self.author, self.close_time = title, time, limit, author, close_time
        self.roster, self.participants, self.is_closed = {}, set(), False
    @discord.ui.button(label="참석/변경하기", style=discord.ButtonStyle.primary, emoji="⚔️", custom_id="join_raid")
    async def join(self, i, b):
        if len(self.roster) >= self.limit and i.user.id not in self.roster: return await i.response.send_message("❌ 정원 초과", ephemeral=True)
        await i.response.send_modal(RaidEntryModal(self))
    @discord.ui.button(label="참여 취소", style=discord.ButtonStyle.gray, custom_id="leave_raid")
    async def leave(self, i, b):
        if i.user.id in self.roster:
            self.roster.pop(i.user.id); self.participants.remove(i.user.id)
            await i.response.edit_message(embed=self.get_embed())
        else: await i.response.send_message("참여 중 아님", ephemeral=True)
    def get_embed(self, closed=False):
        color = 0x5865F2 if not closed else 0x99AAB5
        desc = f"**👤 모집자: {self.author.display_name}**\n📅 **출발 시간:** {self.time}\n👥 **정원:** {self.limit}명\n⏰ **마감 시간:** {self.close_time}"
        embed = discord.Embed(title=f"⚔️ {self.title}", description=desc, color=color)
        list_val = "\n".join([f"> {idx+1}. ({info})" for idx, info in enumerate(self.roster.values())]) if self.roster else "참여 인원 없음"
        embed.add_field(name="참여 명단", value=list_val, inline=False); return embed

class MyBot(commands.Bot):
    def __init__(self): super().__init__(command_prefix="!", intents=discord.Intents.all()); self.db = load_db()
    async def setup_hook(self):
        for g_id in self.db.keys(): self.add_view(RoleAssignView(self, g_id))
        await self.tree.sync()
    async def on_member_join(self, m):
        r_id = self.db.get(str(m.guild.id), {}).get("auto_role_id")
        if r_id:
            role = m.guild.get_role(r_id)
            if role:
                try: await m.add_roles(role)
                except: pass

bot = MyBot()

# --- [명령어 섹션] ---
@bot.tree.command(name="모집")
async def recruit(interaction):
    class RoleSelectView(discord.ui.View):
        @discord.ui.select(cls=discord.ui.RoleSelect, placeholder="📣 알림 보낼 역할 선택")
        async def s(self, i, s): await i.response.send_modal(RecruitModal(role=s.values[0]))
        @discord.ui.button(label="알림 없이 작성", style=discord.ButtonStyle.gray)
        async def no(self, i, b): await i.response.send_modal(RecruitModal(role=None))
    await interaction.response.send_message("모집 설정", view=RoleSelectView(), ephemeral=True)

class RecruitModal(discord.ui.Modal, title='📝 레이드 모집'):
    t = discord.ui.TextInput(label='제목', placeholder='ㅇㅇ 4인 파티')
    tm = discord.ui.TextInput(label='출발 시간', placeholder='오늘 저녁 11시')
    l = discord.ui.TextInput(label='인원', placeholder='숫자만 입력')
    ct = discord.ui.TextInput(label='마감 시간', placeholder='2026-03-04-21:00 / 반드시 이 형식으로 적을 것')
    def __init__(self, role=None): super().__init__(); self.role = role
    async def on_submit(self, i):
        limit_val = re.sub(r'[^0-9]', '', self.l.value)
        limit = int(limit_val) if limit_val else 6
        view = RaidView(self.t.value, self.tm.value, limit, i.user, self.ct.value)
        await i.channel.send(content=f"{self.role.mention if self.role else ''} 🌲 모집 시작!", embed=view.get_embed(), view=view)
        await i.response.send_message("작성 완료", ephemeral=True)

@bot.tree.command(name="자동역할설정")
@app_commands.checks.has_permissions(administrator=True)
async def set_auto_role(i, 역할: discord.Role):
    g_id = str(i.guild.id); bot.db.setdefault(g_id, {})["auto_role_id"] = 역할.id
    save_db(bot.db); await i.response.send_message(f"✅ 자동 역할: **{역할.name}**", ephemeral=True)

@bot.tree.command(name="직업등록")
async def reg_job(i, 이모지:str, 역할명:str):
    g_id = str(i.guild.id); bot.db.setdefault(g_id, {"job_roles": {}})["job_roles"][이모지] = 역할명
    save_db(bot.db); await i.response.send_message("✅ 등록 완료 (재시작 후 반영)", ephemeral=True)

@bot.tree.command(name="역할설정")
async def set_role(i, 문구:str):
    await i.channel.send(content=문구, view=RoleAssignView(bot, i.guild.id))
    await i.response.send_message("✅ 버튼 생성 완료", ephemeral=True)

@bot.tree.command(name="티켓설정")
async def ticket_setup(i, 관리자역할: discord.Role, 상담카테고리명: str, 로그채널명: str):
    log_ch = await i.guild.create_text_channel(name=로그채널명, overwrites={i.guild.default_role: discord.PermissionOverwrite(read_messages=False), 관리자역할: discord.PermissionOverwrite(read_messages=True)})
    view = TicketView(관리자역할.id, 상담카테고리명, log_ch.id)
    bot.add_view(view)
    await i.channel.send(embed=discord.Embed(title="📢 문의 접수", description="버튼을 눌러 티켓을 생성하세요.", color=0x2f3136), view=view)
    await i.response.send_message("✅ 티켓 설정 완료!", ephemeral=True)

@bot.tree.command(name="상담종료")
async def close_ticket(i):
    if "-" not in i.channel.name: return await i.response.send_message("❌ 상담 채널 아님", ephemeral=True)
    await i.response.defer(ephemeral=True); log_ch = None
    async for msg in i.channel.history(oldest_first=True, limit=1):
        if msg.embeds:
            try: log_ch = i.guild.get_channel(int(msg.embeds[0].footer.text.split(": ")[1]))
            except: pass
    history = [f"[{m.created_at.strftime('%m-%d %H:%M')}] {m.author.display_name}: {m.content}" async for m in i.channel.history(limit=None, oldest_first=True)]
    with open("log.txt", "w", encoding="utf-8") as f: f.write("\n".join(history))
    if log_ch: await log_ch.send(f"📂 **종료 기록: {i.channel.name}**", file=discord.File("log.txt"))
    if os.path.exists("log.txt"): os.remove("log.txt")
    await asyncio.sleep(3); await i.channel.delete()

@bot.tree.command(name="역할부여문구_수정")
async def edit_role_msg(i, 수정내용:str):
    async for m in i.channel.history(limit=50):
        if m.author == bot.user and m.components:
            await m.edit(content=수정내용); return await i.response.send_message("✅ 수정 완료!", ephemeral=True)
    await i.response.send_message("❌ 메시지 못 찾음", ephemeral=True)

keep_alive()
bot.run(os.environ.get('TOKEN'))
