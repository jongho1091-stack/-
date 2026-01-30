import discord
from discord.ext import commands
import re
import os
import asyncio
from datetime import datetime, timedelta

# --- 1. 뷰 클래스 (RaidView) ---
class RaidView(discord.ui.View):
    def __init__(self, title, time, limit, duration_min, author):
        super().__init__(timeout=None)
        self.title, self.time, self.limit = title, time, limit
        self.duration_min = duration_min
        self.author = author
        self.end_time = datetime.now() + timedelta(minutes=duration_min)
        self.roles = ["수호성", "검성", "살성", "궁성", "마도성", "정령성", "치유성", "호법성"]
        self.role_icons = {"수호성": "🛡️", "검성": "🗡️", "살성": "⚔️", "궁성": "🏹", "마도성": "🔥", "정령성": "✨", "치유성": "❤️", "호법성": "🪄"}
        self.roster = {role: [] for role in self.roles}
        self.participants = set()
        self.is_closed = False
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
        
        leave_btn = discord.ui.Button(label="취소 (get off)", style=discord.ButtonStyle.gray, custom_id="leave")
        leave_btn.callback = self.leave_callback
        self.add_item(leave_btn)

    def get_embed(self, closed=False):
        curr = sum(len(self.roster[r]) for r in self.roles)
        color = 0x5865F2 if not closed else 0x99AAB5
        status_text = " (모집 종료)" if closed else ""
        
        display_end_time = self.end_time.strftime('%H:%M')
        # [수정] 띄어쓰기 반영: 모집 마감 시간 -> 모집 마감시간
        embed = discord.Embed(title=f"⚔️ {self.title}{status_text}", 
                              description=f"📅 **일시:** {self.time}\n👥 **정원:** {self.limit}명 (현재 {curr}명)\n⏰ **모집 마감시간:** {display_end_time} 까지", 
                              color=color)
        
        embed.set_author(name=f"모집자: {self.author.display_name}", icon_url=self.author.display_avatar.url)
        
        line1 = "".join([f"{self.role_icons[r]} **{r}**: {', '.join(self.roster[r]) if self.roster[r] else '대기 중'}\n" for r in ["수호성", "검성", "살성", "궁성"]])
        embed.add_field(name="\u200b", value=line1, inline=True)
        line2 = "".join([f"{self.role_icons[r]} **{r}**: {', '.join(self.roster[r]) if self.roster[r] else '대기 중'}\n" for r in ["마도성", "정령성", "치유성", "호법성"]])
        embed.add_field(name="\u200b", value=line2, inline=True)
        
        if closed:
            embed.set_footer(text="이 모집은 종료되었습니다.")
        else:
            embed.set_footer(text=f"설정한 모집 기간({self.duration_min}분)이 지나면 자동으로 마감됩니다.")
            
        return embed

    async def close_raid(self, interaction_or_channel):
        if self.is_closed: return
        self.is_closed = True
        for item in self.children: item.disabled = True
        
        embed = self.get_embed(closed=True)
        mentions = " ".join([f"<@{uid}>" for uid in self.participants])
        msg = f"{mentions}\n🏁 **'{self.title}' 모집이 종료되었습니다!**" if mentions else "🏁 **모집이 종료되었습니다.**"
        
        if isinstance(interaction_or_channel, discord.Interaction):
            await interaction_or_channel.edit_original_response(embed=embed, view=self)
            await interaction_or_channel.followup.send(msg)
        else:
            pass 

    async def button_callback(self, interaction: discord.Interaction):
        if self.is_closed:
            return await interaction.response.send_message("이미 종료된 모집입니다.", ephemeral=True)
            
        role_name, user_name = interaction.data['custom_id'], interaction.user.display_name
        user_id = interaction.user.id
        
        for r in self.roster:
            if user_name in self.roster[r]: self.roster[r].remove(user_name)
        
        curr_total = sum(len(self.roster[r]) for r in self.roles)
        if curr_total >= self.limit:
            return await interaction.response.send_message("마감되었습니다.", ephemeral=True)
            
        self.roster[role_name].append(user_name)
        self.participants.add(user_id)
        
        try:
            await self.author.send(f"🔔 **[{self.title}]** 모집 알림: `{user_name}`님이 `{role_name}`으로 참여했습니다.")
        except: pass

        await interaction.response.edit_message(embed=self.get_embed(), view=self)
        
        if sum(len(self.roster[r]) for r in self.roles) >= self.limit:
            await self.close_raid(interaction)

    async def leave_callback(self, interaction: discord.Interaction):
        user_name = interaction.user.display_name
        for r in self.roster:
            if user_name in self.roster[r]: self.roster[r].remove(user_name)
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

# --- 2. 역할 선택 및 모집 모달 ---
class RoleSelectView(discord.ui.View):
    def __init__(self, mode):
        super().__init__(timeout=60)
        self.mode = mode

    @discord.ui.select(cls=discord.ui.RoleSelect, placeholder="알림 보낼 역할 선택 (선택 사항)", min_values=0, max_values=1)
    async def select_role(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        role = select.values[0] if select.values else None
        modal = RecruitModal(role, interaction.message) if self.mode == "recruit" else ScheduleModal(role, interaction.message)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="알림 없이 바로 작성", style=discord.ButtonStyle.gray)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = RecruitModal(None, interaction.message) if self.mode == "recruit" else ScheduleModal(None, interaction.message)
        await interaction.response.send_modal(modal)

class RecruitModal(discord.ui.Modal, title='📝 레이드 모집 작성'):
    def __init__(self, target_role, parent_msg):
        super().__init__()
        self.target_role, self.parent_msg = target_role, parent_msg
        
    title_in = discord.ui.TextInput(label='모집 제목', placeholder='예: 뿔암 정복')
    time_in = discord.ui.TextInput(label='출발 시간', placeholder='예: 23:00')
    limit_in = discord.ui.TextInput(label='모집 인원', placeholder='숫자만 입력')
    duration_in = discord.ui.TextInput(label='모집 기간 (분)', placeholder='예: 30', default="30")

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await self.parent_msg.delete()
            limit_val = int(re.sub(r'[^0-9]', '', self.limit_in.value))
            dur_val = int(re.sub(r'[^0-9]', '', self.duration_in.value))
            
            view = RaidView(self.title_in.value, self.time_in.value, limit_val, dur_val, interaction.user)
            mention = f"{self.target_role.mention}\n" if self.target_role else ""
            
            await interaction.response.send_message(content=f"{mention}🌲 **레이드 모집이 시작되었습니다!**", embed=view.get_embed(), view=view)
            original_msg = await interaction.original_response()

            async def timer():
                await asyncio.sleep(dur_val * 60)
                if not view.is_closed:
                    view.is_closed = True
                    for item in view.children: item.disabled = True
                    mentions = " ".join([f"<@{uid}>" for uid in view.participants])
                    # [수정] 띄어쓰기 반영: 모집 마감시간
                    final_msg = f"{mentions}\n🏁 **모집 마감시간이 되어 '{view.title}' 모집이 종료되었습니다!**" if mentions else "🏁 **모집 마감시간이 되어 모집이 종료되었습니다.**"
                    await original_msg.edit(embed=view.get_embed(closed=True), view=view)
                    await original_msg.reply(final_msg)
            
            asyncio.create_task(timer())

        except Exception as e: await interaction.response.send_message(f"🚨 오류: {e}", ephemeral=True)

class ScheduleModal(discord.ui.Modal, title='📅 일정 체크 작성'):
    def __init__(self, target_role, parent_msg):
        super().__init__()
        self.target_role, self.parent_msg = target_role, parent_msg
    title_in = discord.ui.TextInput(label='일정 제목', placeholder='예: 요새전 지원')
    time_in = discord.ui.TextInput(label='일시', placeholder='예: 토요일 저녁 9시')

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await self.parent_msg.delete()
            embed = discord.Embed(title=f"📅 {self.title_in.value}", description=f"⏰ **시간:** {self.time_in.value}", color=0x2ECC71)
            embed.set_author(name=f"작성자: {interaction.user.display_name}", icon_url=interaction.user.display_avatar.url)
            mention = f"{self.target_role.mention}\n" if self.target_role else ""
            await interaction.response.send_message(content=f"{mention}📅 **일정 확인 부탁드립니다!**", embed=embed)
        except: pass

# --- 3. 봇 메인 ---
class MyBot(commands.Bot):
    def __init__(self): super().__init__(command_prefix="!", intents=discord.Intents.all())
    async def setup_hook(self): await self.tree.sync()

bot = MyBot()
@bot.tree.command(name="모집")
async def recruit(interaction: discord.Interaction):
    await interaction.response.send_message("알림을 보낼 역할이 있나요?", view=RoleSelectView("recruit"))

@bot.tree.command(name="일정")
async def schedule(interaction: discord.Interaction):
    await interaction.response.send_message("알림을 보낼 역할이 있나요?", view=RoleSelectView("schedule"))

bot.run(os.getenv('TOKEN'))
