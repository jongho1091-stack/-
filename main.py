import discord
from discord import app_commands
from discord.ext import commands
import re
import os
import asyncio
from datetime import datetime, timedelta

# --- 1. 레이드 모집 현황 뷰 ---
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
        
        # [2025-08-22] character change 시 "get off" 사용
        leave_btn = discord.ui.Button(label="취소 (get off)", style=discord.ButtonStyle.gray, custom_id="leave")
        leave_btn.callback = self.leave_callback
        self.add_item(leave_btn)

    def get_embed(self, closed=False):
        curr = sum(len(self.roster[r]) for r in self.roles)
        color = 0x5865F2 if not closed else 0x99AAB5
        now = datetime.utcnow() + timedelta(hours=9)
        
        if self.end_time.year > now.year:
            display_time = self.end_time.strftime('%Y/%m/%d %H:%M')
        elif self.end_time.date() > now.date():
            display_time = self.end_time.strftime('%m/%d %H:%M')
        else:
            display_time = self.end_time.strftime('%H:%M')
            
        desc = (
            f"**👤 모집자: {self.author.display_name}**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📅 **출발 시간:** {self.time}\n"
            f"👥 **정원:** {self.limit}명 (현재 {curr}명)\n"
            f"⏰ **모집 마감시간:** {display_time} 까지"
        )
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
        if sum(len(self.roster[r]) for r in self.roles) >= self.limit:
            await self.close_raid(interaction.message)

    async def leave_callback(self, interaction: discord.Interaction):
        name = interaction.user.display_name
        for r in self.roster:
            if name in self.roster[r]: self.roster[r].remove(name)
        if interaction.user.id in self.participants:
            self.participants.remove(interaction.user.id)
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

# --- 2. 입력 모달 ---
class RecruitModal(discord.ui.Modal, title='📝 레이드 모집 작성'):
    title_in = discord.ui.TextInput(label='제목', placeholder='(예시: 뿔암 / 정복 / 일반)')
    time_in = discord.ui.TextInput(label='출발 시간', placeholder='(예시: 23:00 출발)')
    limit_in = discord.ui.TextInput(label='인원', placeholder='숫자만 입력 (예: 6)')
    dur_in = discord.ui.TextInput(
        label='모집 마감시간 (서울 기준)', 
        placeholder='예: 21:00 / 26년 2월 5일 저녁 8시',
        style=discord.TextStyle.paragraph,
        default='26년 2월 5일 저녁 8시',
        required=True
    )

    def __init__(self, role):
        super().__init__()
        self.role = role

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            await interaction.delete_original_response()
            now = datetime.utcnow() + timedelta(hours=9)
            raw_dur = self.dur_in.value.strip()
            
            nums = [int(n) for n in re.findall(r'\d+', raw_dur)]
            target_dt = now
            
            # 오후/저녁 키워드 체크
            add_12 = 12 if any(x in raw_dur for x in ["오후", "저녁", "밤", "pm", "PM"]) else 0

            if "시간" in raw_dur or "분" in raw_dur:
                final_min = 0
                h = re.findall(r'(\d+)시간', raw_dur.replace(" ", ""))
                m = re.findall(r'(\d+)분', raw_dur.replace(" ", ""))
                if h: final_min += int(h[0]) * 60
                if m: final_min += int(m[0])
                target_dt = now + timedelta(minutes=final_min)
            
            elif len(nums) >= 4: # 연/월/일/시 포함 시
                yr = nums[0] + 2000 if nums[0] < 100 else nums[0]
                hr = nums[3]
                if add_12 and hr < 12: hr += 12
                mn = nums[4] if len(nums) > 4 else 0
                target_dt = datetime(yr, nums[1], nums[2], hr, mn)
            
            elif len(nums) == 3: # 월/일/시 포함 시
                hr = nums[2]
                if add_12 and hr < 12: hr += 12
                target_dt = now.replace(month=nums[0], day=nums[1], hour=hr, minute=0, second=0, microsecond=0)
            
            elif ":" in raw_dur or (len(nums) == 1 and len(str(nums[0])) >= 3):
                t_str = str(nums[0]).zfill(4) if len(nums) == 1 else f"{nums[0]:02}{nums[1]:02}"
                hr = int(t_str[:2])
                if add_12 and hr < 12: hr += 12
                target_dt = now.replace(hour=hr, minute=int(t_str[2:]), second=0, microsecond=0)
                if target_dt < now: target_dt += timedelta(days=1)
            else:
                target_dt = now + timedelta(minutes=(nums[0] if nums else 30))

            if target_dt <= now: target_dt = now + timedelta(minutes=30)
            sleep_sec = (target_dt - now).total_seconds()

            l_str = re.sub(r'[^0-9]', '', self.limit_in.value)
            limit = int(l_str) if l_str else 6
            view = RaidView(self.title_in.value, self.time_in.value, limit, target_dt, interaction.user)
            ment = self.role.mention if self.role else ""
            sent_msg = await interaction.followup.send(content=f"{ment} 🌲 **레이드 모집이 시작되었습니다!**", embed=view.get_embed(), view=view)
            
            async def timer():
                await asyncio.sleep(max(0, sleep_sec))
                await view.close_raid(sent_msg)
            asyncio.create_task(timer())
            
        except Exception as e:
            await interaction.followup.send(f"🚨 시간 분석 오류: {e}", ephemeral=True)

# --- 3. 역할 선택 뷰 및 봇 실행 ---
class RoleSelectView(discord.ui.View):
    def __init__(self): super().__init__(timeout=60)
    @discord.ui.select(cls=discord.ui.RoleSelect, placeholder="📣 알림 보낼 역할을 선택하세요")
    async def select_role(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        await interaction.response.send_modal(RecruitModal(select.values[0]))
    @discord.ui.button(label="알림 없이 바로 작성", style=discord.ButtonStyle.gray)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RecruitModal(None))

class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=discord.Intents.all())
    async def setup_hook(self): await self.tree.sync()

bot = MyBot()
@bot.tree.command(name="모집", description="레이드 모집글을 작성합니다.")
async def recruit(interaction: discord.Interaction):
    guide = (
        "🌲 **마감 시간 입력 팁**\n"
        "• `21:00` : 오늘 밤 9시 마감\n"
        "• `26년 2월 5일 저녁 8시` : 날짜/시간 지정\n"
        "• `1시간 30분` : 지금부터 계산\n"
    )
    await interaction.response.send_message(guide, view=RoleSelectView(), ephemeral=True)

bot.run(os.getenv('TOKEN'))
