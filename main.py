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

# --- DB 설정 ---
DB_FILE = "guild_settings.json"
def save_db(data):
    with open(DB_FILE, 'w', encoding='utf-8') as f: json.dump(data, f, ensure_ascii=False, indent=4)
def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, 'r', encoding='utf-8') as f: 
            data = json.load(f)
            if "ticket_admin_role" not in data: data["ticket_admin_role"] = None
            return data
    return {"auto_role": None, "job_roles": {}, "setup_msg_id": None, "setup_chan_id": None, "ticket_admin_role": None}

# --- [역할] 관련 기능 (보존) ---
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
        for emoji, role_name in guild_data.get("job_roles", {}).items():
            btn = discord.ui.Button(label=role_name, emoji=emoji, style=discord.ButtonStyle.secondary, custom_id=f"role_{guild_id}_{role_name}")
            btn.callback = self.make_cb(emoji, role_name, guild_data.get("job_roles", {}))
            self.add_item(btn)
    def make_cb(self, emoji, role_name, job_roles):
        async def cb(i): await i.response.send_modal(NicknameModal(emoji, role_name, job_roles))
        return cb

# --- [레이드 모집] 기능 (무녀/93 버전 + 가이드 문구 수정) ---
class RaidEntryModal(discord.ui.Modal, title='⚔️ 레이드 참석 정보 입력'):
    job = discord.ui.TextInput(label='직업', placeholder='(줄임말 없이 작성)', min_length=2, max_length=10)
    char_name = discord.ui.TextInput(label='캐릭터명', placeholder='(ex.토끼공듀)', min_length=1, max_length=20)
    power = discord.ui.TextInput(label='전투력', placeholder='(ex.12+)', min_length=1, max_length=10)
    
    def __init__(self, raid_view): super().__init__(); self.raid_view = raid_view
    
    async def on_submit(self, interaction: discord.Interaction):
        if self.raid_view.is_closed: return await interaction.response.send_message("❌ 이미 모집이 마감되었습니다.", ephemeral=True)
        user_id = interaction.user.id
        self.raid_view.roster[user_id] = f"{self.job.value} / {self.char_name.value} / {self.power.value}"
        self.raid_view.participants.add(user_id)
        await interaction.response.edit_message(embed=self.raid_view.get_embed())
        try:
            alert = await interaction.channel.send(f"🔔 {self.raid_view.author.mention}님, **{self.char_name.value}** 참석 ({self.job.value})")
            await alert.delete(delay=3)
        except: pass

class RaidView(discord.ui.View):
    def __init__(self, title, time, limit, end_dt, author):
        super().__init__(timeout=None)
        self.title, self.time, self.limit, self.end_time, self.author = title, time, limit, end_dt, author
        self.roster, self.participants, self.is_closed = {}, set(), False
        self.create_buttons()

    def create_buttons(self):
        j = discord.ui.Button(label="참석/변경하기", style=discord.ButtonStyle.primary, emoji="⚔️", custom_id="join_raid")
        j.callback = self.join_callback; self.add_item(j)
        l = discord.ui.Button(label="참여 취소", style=discord.ButtonStyle.gray, custom_id="leave_raid")
        l.callback = self.leave_callback; self.add_item(l)
        c = discord.ui.Button(label="모집 마감 / 작성자 전용", style=discord.ButtonStyle.danger, emoji="🛑", custom_id="force_close")
        c.callback = self.force_close_callback; self.add_item(c)

    def get_embed(self, closed=False):
        curr = len(self.roster); color = 0x5865F2 if not closed else 0x99AAB5
        now = datetime.now(UTC) + timedelta(hours=9)
        display_time = self.end_time.strftime('%m/%d %H:%M') if self.end_time.date() > now.date() else self.end_time.strftime('%H:%M')
        desc = (f"**👤 모집자: {self.author.display_name}**\n━━━━━━━━━━━━━━━━━━━━\n"
                f"📅 **출발 시간:** {self.time}\n👥 **정원:** {self.limit}명 (현재 {curr}명)\n⏰ **모집 마감:** {display_time} 까지")
        embed = discord.Embed(title=f"⚔️ {self.title}{' (모집 종료)' if closed else ''}", description=desc, color=color)
        list_val = "\n".join([f"> {idx+1}. ({info})" for idx, info in enumerate(self.roster.values())]) if self.roster else "> 현재 참여 인원 없음"
        embed.add_field(name="👥 현재 참여 명단 (실시간)", value=list_val, inline=False); return embed

    async def join_callback(self, i):
        if self.is_closed: return
        if len(self.roster) >= self.limit and i.user.id not in self.roster: return await i.response.send_message("❌ 정원이 가득 찼습니다.", ephemeral=True)
        await i.response.send_modal(RaidEntryModal(self))

    async def leave_callback(self, i):
        if i.user.id in self.roster:
            self.roster.pop(i.user.id); self.participants.remove(i.user.id)
            try:
                alert = await i.channel.send(f"⚪ {self.author.mention}님, **{i.user.display_name}** 참여 취소 (get off)")
                await alert.delete(delay=3)
            except: pass
            await i.response.edit_message(embed=self.get_embed())
        else: await i.response.send_message("참여 중이 아닙니다.", ephemeral=True)

    async def force_close_callback(self, i):
        if i.user.id != self.author.id: return await i.response.send_message("❌ 작성자만 마감할 수 있습니다!", ephemeral=True)
        await i.response.defer(ephemeral=True); await self.close_raid(i.message)

    async def close_raid(self, message):
        if self.is_closed: return
        self.is_closed = True; [setattr(item, 'disabled', True) for item in self.children]
        try:
            await message.edit(embed=self.get_embed(closed=True), view=self)
            mentions = " ".join([f"<@{u}>" for u in self.participants])
            if mentions: await message.reply(f"{mentions}\n🏁 **'{self.title}' 모집이 종료되었습니다!**")
        except: pass

class RecruitModal(discord.ui.Modal, title='📝 레이드 모집'):
    t_in = discord.ui.TextInput(label='제목', placeholder='ㅇㅇ 4인 파티')
    tm_in = discord.ui.TextInput(label='출발 시간', placeholder='오늘 저녁 11시')
    l_in = discord.ui.TextInput(label='인원', placeholder='숫자만 입력')
    d_in = discord.ui.TextInput(label='모집 마감 시간', placeholder='2026-03-04-21:00 / 반드시 이 형식으로 적을 것')
    
    def __init__(self, role=None, setup_i=None): super().__init__(); self.role, self.setup_i = role, setup_i
    
    async def on_submit(self, i):
        await i.response.defer(ephemeral=True); val = self.d_in.value.strip(); target_dt = None; nums = re.findall(r'\d+', val)
        if len(nums) >= 4:
            try:
                y = int(nums[0]); y = y + 2000 if y < 100 else y
                target_dt = datetime(y, int(nums[1]), int(nums[2]), int(nums[3]), int(nums[4]) if len(nums) >= 5 else 0, tzinfo=UTC) - timedelta(hours=9)
            except: pass
        if not target_dt: target_dt = datetime.now(UTC) + timedelta(minutes=30)
        limit = int(re.sub(r'[^0-9]', '', self.l_in.value)) if re.sub(r'[^0-9]', '', self.l_in.value) else 6
        view = RaidView(self.t_in.value, self.tm_in.value, limit, target_dt + timedelta(hours=9), i.user)
        sent = await i.channel.send(content=f"{self.role.mention if self.role else ''} 🌲 **모집 시작!**", embed=view.get_embed(), view=view)
        if self.setup_i: 
            try: await self.setup_i.delete_original_response()
            except: pass
        async def timer(): await asyncio.sleep(max(0, (target_dt - datetime.now(UTC)).total_seconds())); await view.close_raid(sent)
        asyncio.create_task(timer())

# --- [티켓] 관련 기능 (보존) ---
class TicketView(discord.ui.View):
    def __init__(self, bot): super().__init__(timeout=None); self.bot = bot
    async def create_ticket(self, interaction, category):
        guild, member = interaction.guild, interaction.user
        chan_name = f"{category}-{member.display_name[:10]}"
        admin_role_id = self.bot.db.get("ticket_admin_role")
        admin_role = guild.get_role(admin_role_id) if admin_role_id else None
        over = {guild.default_role: discord.PermissionOverwrite(read_messages=False), member: discord.PermissionOverwrite(read_messages=True, send_messages=True), guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)}
        if admin_role: over[admin_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        ticket_chan = await guild.create_text_channel(chan_name, overwrites=over)
        emb = discord.Embed(title=f"🎫 {category} 접수", description=f"{member.mention}님, 내용을 남겨주세요.", color=0x5865F2)
        close_v = discord.ui.View(timeout=None); close_b = discord.ui.Button(label="티켓 닫기", style=discord.ButtonStyle.secondary)
        async def cb(i): await i.response.send_message("3초 후 채널을 삭제(get off)합니다."); await asyncio.sleep(3); await i.channel.delete()
        close_b.callback = cb; close_v.add_item(close_b); await ticket_chan.send(embed=emb, view=close_v)
        await interaction.response.send_message(f"✅ 티켓 생성!", ephemeral=True)

    @discord.ui.button(label="문의/건의하기", style=discord.ButtonStyle.success, emoji="🙋", custom_id="btn_inquiry")
    async def inquiry(self, i): await self.create_ticket(i, "문의-건의")
    @discord.ui.button(label="신고하기", style=discord.ButtonStyle.danger, emoji="🚨", custom_id="btn_report")
    async def report(self, i): await self.create_ticket(i, "신고")

# --- 봇 설정 및 실행 ---
class MyBot(commands.Bot):
    def __init__(self): super().__init__(command_prefix="!", intents=discord.Intents.all()); self.db = load_db()
    async def setup_hook(self): 
        self.add_view(TicketView(self))
        for g_id in self.db.keys():
            if g_id.isdigit(): self.add_view(RoleAssignView(self, g_id))
        await self.tree.sync()

bot = MyBot()

@bot.tree.command(name="모집")
async def recruit(interaction):
    class RoleSelectView(discord.ui.View):
        @discord.ui.select(cls=discord.ui.RoleSelect, placeholder="📣 알림 보낼 역할 선택")
        async def s_role(self, i, s): await i.response.send_modal(RecruitModal(role=s.values[0], setup_i=i))
        @discord.ui.button(label="알림 없이 작성", style=discord.ButtonStyle.gray)
        async def no_m(self, i, b): await i.response.send_modal(RecruitModal(role=None, setup_i=i))
    await interaction.response.send_message("모집 설정 중...", view=RoleSelectView(), ephemeral=True)

@bot.tree.command(name="역할설정")
async def set_role(i, 문구:str):
    await i.channel.send(content=문구, view=RoleAssignView(bot, i.guild.id))
    await i.response.send_message("✅ 버튼 생성 완료", ephemeral=True)

@bot.tree.command(name="티켓설정")
@app_commands.checks.has_permissions(administrator=True)
async def setup_ticket(interaction, 내용: str, 관리역할: discord.Role):
    bot.db["ticket_admin_role"] = 관리역할.id; save_db(bot.db)
    await interaction.channel.send(content=내용, view=TicketView(bot))
    await interaction.response.send_message(f"✅ 티켓 설정 완료!", ephemeral=True)

keep_alive()
bot.run(os.environ.get('TOKEN'))
