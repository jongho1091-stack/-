import discord
from discord import app_commands
from discord.ext import commands
import re
import os
import asyncio
import json
from datetime import datetime, timedelta, UTC
from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

def run():
    app.run(host='0.0.0.0', port=10000)

def keep_alive():
    t = Thread(target=run)
    t.start()

class RaidView(discord.ui.View):
    def __init__(self, title, time, limit, target_dt, creator):
        super().__init__(timeout=None)
        self.title = title
        self.time = time
        self.limit = limit
        self.target_dt = target_dt
        self.creator = creator
        self.participants = [creator.display_name]

    def get_embed(self):
        embed = discord.Embed(title=f"🌲 {self.title}", color=0x2f3136)
        embed.add_field(name="⏰ 출발 시간", value=f"`{self.time}`", inline=True)
        embed.add_field(name="👥 모집 인원", value=f"`{len(self.participants)} / {self.limit}`", inline=True)
        embed.add_field(name="⌛ 마감 시간", value=f"<t:{int(self.target_dt.timestamp())}:F>", inline=False)
        
        plist = "\n".join([f"· {p}" for p in self.participants]) if self.participants else "없음"
        embed.add_field(name="📝 참여자 명단", value=f"```\n{plist}\n```", inline=False)
        embed.set_footer(text=f"모집자: {self.creator.display_name}")
        return embed

    @discord.ui.button(label="참석/변경하기", style=discord.ButtonStyle.green, custom_id="raid_join")
    async def join(self, i: discord.Interaction, button: discord.ui.Button):
        name = i.user.display_name
        if name in self.participants:
            self.participants.remove(name)
        else:
            if len(self.participants) < self.limit:
                self.participants.append(name)
            else:
                return await i.response.send_message("정원이 초과되었습니다.", ephemeral=True)
        
        await i.response.edit_message(embed=self.get_embed(), view=self)

    async def close_raid(self, message):
        for child in self.children:
            child.disabled = True
        embed = self.get_embed()
        embed.title = f"❌ [마감] {self.title}"
        embed.color = discord.Color.red()
        try:
            await message.edit(embed=embed, view=self)
        except:
            pass
        self.stop()

class RecruitModal(discord.ui.Modal, title='📝 레이드 모집'):
    t_in = discord.ui.TextInput(label='제목', placeholder='(ex: 루드라 갈 사람)')
    tm_in = discord.ui.TextInput(label='출발 시간', placeholder='(ex: 21시)')
    l_in = discord.ui.TextInput(label='인원', placeholder='숫자만 입력 (ex: 6)')
    d_in = discord.ui.TextInput(
        label='모집 마감 시간', 
        placeholder='2026-03-04-21:00 (이 형식과 동일하게 쓸 것)'
    )
    
    def __init__(self, role=None, setup_i=None):
        super().__init__()
        self.role = role
        self.setup_i = setup_i
    
    async def on_submit(self, i: discord.Interaction):
        await i.response.defer(ephemeral=True)
        val = self.d_in.value.strip()
        target_dt = None
        nums = re.findall(r'\d+', val)
        
        if len(nums) >= 4:
            try:
                y = int(nums[0]); y = y + 2000 if y < 100 else y
                target_dt = datetime(y, int(nums[1]), int(nums[2]), int(nums[3]), int(nums[4]) if len(nums) >= 5 else 0, tzinfo=UTC) - timedelta(hours=9)
            except:
                pass
        
        if not target_dt:
            target_dt = datetime.now(UTC) + timedelta(minutes=30)

        limit_val = re.sub(r'[^0-9]', '', self.l_in.value)
        limit = int(limit_val) if limit_val else 6
        
        view = RaidView(self.t_in.value, self.tm_in.value, limit, target_dt + timedelta(hours=9), i.user)
        sent = await i.channel.send(content=f"{self.role.mention if self.role else ''} 🌲 **모집 시작!**", embed=view.get_embed(), view=view)
        
        if self.setup_i:
            try: await self.setup_i.delete_original_response()
            except: pass
            
        async def timer():
            wait_sec = (target_dt - datetime.now(UTC)).total_seconds()
            if wait_sec > 0:
                await asyncio.sleep(wait_sec)
            await view.close_raid(sent)
            
        asyncio.create_task(timer())

class TicketView(discord.ui.View):
    def __init__(self, btn1_label, btn2_label):
        super().__init__(timeout=None)
        self.add_item(TicketButton(btn1_label, discord.ButtonStyle.primary, "ticket_1"))
        self.add_item(TicketButton(btn2_label, discord.ButtonStyle.danger, "ticket_2"))

class TicketButton(discord.ui.Button):
    def __init__(self, label, style, custom_id):
        super().__init__(label=label, style=style, custom_id=custom_id)

    async def callback(self, i: discord.Interaction):
        guild = i.guild
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            i.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        channel = await guild.create_text_channel(name=f"티켓-{i.user.display_name}", overwrites=overwrites)
        await i.response.send_message(f"{channel.mention} 채널이 생성되었습니다.", ephemeral=True)
        
        embed = discord.Embed(title="🎫 티켓 문의", description=f"**{i.user.mention}**님, 무엇을 도와드릴까요?\n이 채널은 3분 후 자동으로 삭제됩니다.", color=0x2f3136)
        await channel.send(embed=embed)
        
        await asyncio.sleep(180)
        try: await channel.delete()
        except: pass

class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        keep_alive()
        self.add_view(TicketView("문의/건의하기", "신고하기"))
        await self.tree.sync()

bot = MyBot()

@bot.tree.command(name="모집", description="레이드 모집을 시작합니다.")
async def recruit(i: discord.Interaction, 역할: discord.Role = None):
    await i.response.send_modal(RecruitModal(role=역할, setup_i=i))

@bot.tree.command(name="티켓설정", description="티켓 생성 버튼을 설정합니다.")
@app_commands.describe(버튼1="첫 번째 버튼 이름", 버튼2="두 번째 버튼 이름")
async def ticket_setup(i: discord.Interaction, 버튼1: str, 버튼2: str):
    view = TicketView(버튼1, 버튼2)
    embed = discord.Embed(title="🎫 티켓 시스템", description="아래 버튼을 클릭하여 티켓을 생성하세요.", color=0x2f3136)
    await i.channel.send(embed=embed, view=view)
    await i.response.send_message("티켓 설정 완료!", ephemeral=True)
    await asyncio.sleep(3)
    try: await i.delete_original_response()
    except: pass

bot.run(os.environ['TOKEN'])
