import discord
from discord.ext import commands
from discord import app_commands
import re
import os

# --- 뷰 클래스 (RaidView, ScheduleView) ---
class RaidView(discord.ui.View):
    def __init__(self, title, time, limit):
        super().__init__(timeout=None)
        self.title, self.time, self.limit = title, time, limit
        self.roles = ["수호성", "검성", "살성", "궁성", "마도성", "정령성", "치유성", "호법성"]
        self.role_icons = {"수호성": "🛡️", "검성": "🗡️", "살성": "⚔️", "궁성": "🏹", "마도성": "🔥", "정령성": "✨", "치유성": "❤️", "호법성": "🪄"}
        self.roster = {role: [] for role in self.roles}
        self.create_buttons()

    def create_buttons(self):
        role_info = {
            "수호성": {"s": discord.ButtonStyle.primary, "e": "🛡️"},
            "검성": {"s": discord.ButtonStyle.primary, "e": "🗡️"},
            "살성": {"s": discord.ButtonStyle.success, "e": "⚔️"},
            "궁성": {"s": discord.ButtonStyle.success, "e": "🏹"},
            "마도성": {"s": discord.ButtonStyle.danger, "e": "🔥"},
            "정령성": {"s": discord.ButtonStyle.danger, "e": "✨"},
            "치유성": {"s": discord.ButtonStyle.secondary, "e": "❤️"},
            "호법성": {"s": discord.ButtonStyle.secondary, "e": "🪄"}
        }
        for role in self.roles:
            btn = discord.ui.Button(label=role, style=role_info[role]["s"], emoji=role_info[role]["e"], custom_id=role)
            btn.callback = self.button_callback
            self.add_item(btn)
        
        # "get off" 규칙 준수
        leave_btn = discord.ui.Button(label="취소 (get off)", style=discord.ButtonStyle.gray, custom_id="leave")
        leave_btn.callback = self.leave_callback
        self.add_item(leave_btn)

    def get_embed(self):
        curr = sum(len(self.roster[r]) for r in self.roles)
        embed = discord.Embed(title=f"⚔️ {self.title}", description=f"📅 **일시:** {self.time}\n👥 **정원:** {self.limit}명 (현재 {curr}명)", color=0x5865F2)
        line1 = ""
        for r in ["수호성", "검성", "살성", "궁성"]:
            m = ", ".join(self.roster[r]) if self.roster[r] else "대기 중"
            line1 += f"{self.role_icons[r]} **{r}**: {m}\n"
        embed.add_field(name="\u200b", value=line1, inline=True)
        line2 = ""
        for r in ["마도성", "정령성", "치유성", "호법성"]:
            m = ", ".join(self.roster[r]) if self.roster[r] else "대기 중"
            line2 += f"{self.role_icons[r]} **{r}**: {m}\n"
        embed.add_field(name="\u200b", value=line2, inline=True)
        return embed

    async def button_callback(self, interaction: discord.Interaction):
        role_name, user_name = interaction.data['custom_id'], interaction.user.display_name
        for r in self.roster:
            if user_name in self.roster[r]: self.roster[r].remove(user_name)
        if sum(len(self.roster[r]) for r in self.roles) >= self.limit:
            return await interaction.response.send_message("마감되었습니다.", ephemeral=True)
        self.roster[role_name].append(user_name)
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def leave_callback(self, interaction: discord.Interaction):
        user_name = interaction.user.display_name
        for r in self.roster:
            if user_name in self.roster[r]: self.roster[r].remove(user_name)
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

class ScheduleView(discord.ui.View):
    def __init__(self, title, time):
        super().__init__(timeout=None)
        self.title, self.time = title, time
        self.roster = {"참석 가능": [], "참석 불가능": []}
    def get_embed(self):
        embed = discord.Embed(title=f"📅 {self.title}", description=f"⏰ **시간:** {self.time}", color=0x2ECC71)
        for role, members in self.roster.items():
            embed.add_field(name=f"{role} ({len(members)}명)", value=", ".join(members) if members else "대기 중", inline=False)
        return embed
    @discord.ui.button(label="참석 가능", style=discord.ButtonStyle.success, emoji="✅")
    async def confirm(self, interaction, button):
        name = interaction.user.display_name
        if name in self.roster["참석 불가능"]: self.roster["참석 불가능"].remove(name)
        if name not in self.roster["참석 가능"]: self.roster["참석 가능"].append(name)
        await interaction.response.edit_message(embed=self.get_embed())
    @discord.ui.button(label="참석 불가능", style=discord.ButtonStyle.danger, emoji="❌")
    async def deny(self, interaction, button):
        name = interaction.user.display_name
        if name in self.roster["참석 가능"]: self.roster["참석 가능"].remove(name)
        if name not in self.roster["참석 불가능"]: self.roster["참석 불가능"].append(name)
        await interaction.response.edit_message(embed=self.get_embed())
    @discord.ui.button(label="취소 (get off)", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction, button):
        name = interaction.user.display_name
        for r in self.roster:
            if name in self.roster[r]: self.roster[r].remove(name)
        await interaction.response.edit_message(embed=self.get_embed())

# --- 모달 클래스 (입력창) ---
class RecruitModal(discord.ui.Modal, title='📝 레이드 모집 작성'):
    title_in = discord.ui.TextInput(label='모집 제목', placeholder='예: 뿔암 정복', required=True)
    time_in = discord.ui.TextInput(label='출발 시간', placeholder='예: 23:00', required=True)
    limit_in = discord.ui.TextInput(label='모집 인원', placeholder='숫자만 입력 (예: 8)', required=True)
    # ✨ 선택 사항으로 설정 (required=False)
    role_id_in = discord.ui.TextInput(label='알림 보낼 역할 ID (선택)', placeholder='비워두면 알림 없이 작성됩니다.', required=False)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            val = re.sub(r'[^0-9]', '', self.limit_in.value)
            view = RaidView(self.title_in.value, self.time_in.value, int(val))
            mention_msg = f"<@&{re.sub(r'[^0-9]', '', self.role_id_in.value)}>\n" if self.role_id_in.value else ""
            await interaction.response.send_message(content=f"{mention_msg}🌲 **레이드 모집이 시작되었습니다!**", embed=view.get_embed(), view=view)
        except Exception as e: await interaction.response.send_message(f"🚨 오류: {e}", ephemeral=True)

class ScheduleModal(discord.ui.Modal, title='📅 일정 체크 작성'):
    title_in = discord.ui.TextInput(label='일정 제목', placeholder='예: 요새전 지원', required=True)
    time_in = discord.ui.TextInput(label='일시', placeholder='예: 토요일 저녁 9시', required=True)
    # ✨ 선택 사항으로 설정 (required=False)
    role_id_in = discord.ui.TextInput(label='알림 보낼 역할 ID (선택)', placeholder='비워두면 알림 없이 작성됩니다.', required=False)

    async def on_submit(self, interaction: discord.Interaction):
        view = ScheduleView(self.title_in.value, self.time_in.value)
        mention_msg = f"<@&{re.sub(r'[^0-9]', '', self.role_id_in.value)}>\n" if self.role_id_in.value else ""
        await interaction.response.send_message(content=f"{mention_msg}📅 **일정 확인 부탁드립니다!**", embed=view.get_embed(), view=view)

# --- 봇 설정 및 실행 ---
class MyBot(commands.Bot):
    def __init__(self): super().__init__(command_prefix="!", intents=discord.Intents.all())
    async def setup_hook(self): await self.tree.sync()

bot = MyBot()
@bot.tree.command(name="모집")
async def recruit(interaction: discord.Interaction): await interaction.response.send_modal(RecruitModal())
@bot.tree.command(name="일정")
async def schedule(interaction: discord.Interaction): await interaction.response.send_modal(ScheduleModal())

bot.run(os.getenv('TOKEN'))
