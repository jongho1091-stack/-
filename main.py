import discord
from discord.ext import commands
import re
import os
import asyncio
from datetime import datetime, timedelta

# --- 1. 뷰 클래스 ---
class RaidView(discord.ui.View):
    def __init__(self, title, time, limit, duration_min, author):
        super().__init__(timeout=None)
        self.title, self.time, self.limit = title, time, limit
        self.duration_min = duration_min
        self.author = author
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
        
        leave_btn = discord.ui.Button(label="취소 (get off)", style=discord.ButtonStyle.gray, custom_id="leave")
        leave_btn.callback = self.leave_callback
        self.add_item(leave_btn)

    def get_embed(self, closed=False):
        curr = sum(len(self.roster[r]) for r in self.roles)
        color = 0x5865F2 if not closed else 0x99AAB5
        display_time = self.end_time.strftime('%H:%M')
        
        embed = discord.Embed(title=f"⚔️ {self.title}{' (종료)' if closed else ''}", 
                              description=f"📅 일시: {self.time}\n👥 정원: {self.limit}명 ({curr}명)\n⏰ 모집 마감시간: {display_time} 까지", color=color)
        embed.set_author(name=f"모집자: {self.author.display_name}", icon_url=self.author.display_avatar.url)
        
        for i in range(0, 8, 4):
            val = "".join([f"{self.role_icons[r]} **{r}**: {', '.join(self.roster[r]) if self.roster[r] else '대기'}\n" for r in self.roles[i:i+4]])
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
            try: await self.author.send(f"🔔 {self.title}: {name}({role}) 참여")
            except: pass
        await interaction.response.edit_message(embed=self.get_embed())

    async def leave_callback(self, interaction: discord.Interaction):
        name = interaction.user.display_name
        for r in self.roster:
            if name in self.roster[r]: self.roster[r].remove(name)
        await interaction.response.edit_message(embed=self.get_embed())

# --- 2. 모달 및 뷰 ---
class RecruitModal(discord.ui.Modal, title='📝 레이드 모집'):
    title_in = discord.ui.TextInput(label='제목')
    time_in = discord.ui.TextInput(label='시간')
    limit_in = discord.ui.TextInput(label='인원')
    dur_in = discord.ui.TextInput(label='마감(분)', default="30")

    def __init__(self, role, msg):
        super().__init__()
        self.role, self.msg = role, msg

    async def on_submit(self, interaction: discord.Interaction):
        await self.msg.delete()
        limit = int(re.sub(r'[^0-9]', '', self.limit_in.value))
        dur = int(re.sub(r'[^0-9]', '', self.dur_in.value))
        view = RaidView(self.title_in.value, self.time_in.value, limit, dur, interaction.user)
        ment = self.role.mention if self.role else ""
        await interaction.response.send_message(content=f"{ment} 🌲 모집 시작!", embed=view.get_embed(), view=view)
        
        msg = await interaction.original_response()
        await asyncio.sleep(dur * 60)
        if not view.is_closed:
            view.is_closed = True
            for b in view.children: b.disabled = True
            uids = " ".join([f"<@{u}>" for u in view.participants])
            await msg.edit(embed=view.get_embed(True), view=view)
            if uids: await msg.reply(f"{uids}\n🏁 모집 마감시간이 되어 종료되었습니다!")

class RoleSelectView(discord.ui.View):
    def __init__(self): super().__init__(timeout=60)
    @discord.ui.select(cls=discord.ui.RoleSelect, placeholder="알림 역할 선택")
    async def s(self, interaction, select):
        await interaction.response.send_modal(RecruitModal(select.values[0] if select.values else None, interaction.message))
    @discord.ui.button(label="바로 작성", style=discord.ButtonStyle.gray)
    async def b(self, interaction, button):
        await interaction.response.send_modal(RecruitModal(None, interaction.message))

# --- 3. 봇 실행 ---
class MyBot(commands.Bot):
    def __init__(self): super().__init__(command_prefix="!", intents=discord.Intents.all())
    async def setup_hook(self): await self.tree.sync()

bot = MyBot()
@bot.tree.command(name="모집")
async def recruit(interaction: discord.Interaction):
    await interaction.response.send_message("알림 보낼 역할을 선택하세요.", view=RoleSelectView())

bot.run(os.getenv('TOKEN'))
