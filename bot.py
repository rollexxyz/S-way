import os
import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
import requests
import io

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Get bot token from environment variable
BOT_TOKEN = os.environ.get('BOT_TOKEN')

if not BOT_TOKEN:
    logger.error("❌ BOT_TOKEN environment variable not set!")
    raise ValueError("Please set BOT_TOKEN environment variable")

# ========== Original SWAPI Functions ==========
def get_all_batches():
    """Fetch all available batches"""
    url = "https://hackerfreesw.vercel.app/batches"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Error fetching batches: {e}")
        return []

def get_batch_details(batch_id):
    """Fetch detailed information for a specific batch"""
    url = f"https://hackerfreesw.vercel.app/extract/batch_id={batch_id}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Error fetching batch details: {e}")
        return None

def get_video_link(video_links):
    """Get video link (720p > 480p > 360p > 240p)"""
    for quality in ['720p', '480p', '360p', '240p']:
        for link in video_links:
            if link.get('quality') == quality:
                return link.get('url')
    return ""

def extract_links(batch_details):
    """Extract all links"""
    all_links = []
    
    # Topics ke videos aur PDFs
    for topic in batch_details.get("topics", []):
        topic_name = topic.get("topicName", "")
        
        for lecture in topic.get("lectures", []):
            # Video link
            video_url = get_video_link(lecture.get("videoLinks", []))
            if video_url:
                all_links.append({
                    "type": "video",
                    "topic": topic_name,
                    "title": lecture.get("videoTitle", ""),
                    "url": video_url
                })
            
            # PDF links from lecture
            for pdf in lecture.get("pdfLinks", []):
                all_links.append({
                    "type": "pdf",
                    "topic": topic_name,
                    "title": pdf.get("name", ""),
                    "url": pdf.get("url", "")
                })
    
    # Study material PDFs
    for material in batch_details.get("studyMaterial", []):
        for pdf in material.get("pdfs", []):
            all_links.append({
                "type": "study_pdf",
                "topic": material.get("topic", "Study Material"),
                "title": pdf.get("title", ""),
                "url": pdf.get("link", "")
            })
    
    return all_links

# ========== Telegram Bot Handlers ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /start is issued."""
    user = update.effective_user
    await update.message.reply_text(
        f'👋 Hello {user.first_name}!\n\n'
        'Welcome to Batch Link Extractor Bot\n\n'
        'Use /batches to see available batches\n'
        'Use /help for more information'
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /help is issued."""
    help_text = """
📚 *Available Commands:*
    
/batches - Show all available batches
/help - Show this help message
/cancel - Cancel current operation

⚙️ *How to use:*
1. Use /batches to see all batches
2. Click on a batch button
3. Bot will extract all links
4. Download the text file with all links

🔗 *Bot extracts:*
• Video links (720p, 480p, etc.)
• PDF lecture materials
• Study materials

🔄 *Status:* ✅ Online
🤖 *Deployed on:* Render.com
"""
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def list_batches(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all available batches with inline buttons."""
    await update.message.reply_text("📦 Fetching batches... Please wait...")
    
    batches = get_all_batches()
    
    if not batches:
        await update.message.reply_text("❌ No batches found!")
        return
    
    # Create inline keyboard with batches
    keyboard = []
    for batch in batches[:30]:  # Limit to 30 batches
        batch_name = batch.get('batchName', 'Unknown Batch')[:25]
        batch_id = batch.get('batchId', '')
        price = batch.get('discountPrice', 'N/A')
        
        button_text = f"{batch_name} - ₹{price}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"batch_{batch_id}")])
    
    # Add cancel button
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"📚 *Available Batches ({len(batches)})*\n"
        "Click on a batch to extract links:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button callbacks."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == "cancel":
        await query.edit_message_text("❌ Operation cancelled.")
        return
    
    if data.startswith("batch_"):
        batch_id = data.replace("batch_", "")
        await extract_and_send_batch(query, batch_id)

async def extract_and_send_batch(query, batch_id):
    """Extract batch links and send as file."""
    try:
        # Get batch details
        batches = get_all_batches()
        batch_info = next((b for b in batches if b.get('batchId') == batch_id), None)
        
        if not batch_info:
            await query.edit_message_text("❌ Batch not found!")
            return
        
        batch_name = batch_info.get('batchName', 'Unknown')
        batch_image = batch_info.get('batchThumb', '')
        
        await query.edit_message_text(f"⏳ Extracting links for: *{batch_name}*...", parse_mode='Markdown')
        
        # Get batch details
        details = get_batch_details(batch_id)
        if not details:
            await query.edit_message_text("❌ Failed to get batch details!")
            return
        
        # Extract links
        links = extract_links(details)
        
        if not links:
            await query.edit_message_text("❌ No links found in this batch!")
            return
        
        # Prepare text file
        filename = f"{batch_name.replace(' ', '_').replace('/', '-')[:50]}.txt"
        file_content = f"Batch: {batch_name}\n"
        file_content += f"Batch Image: {batch_image}\n\n"
        
        # Add links to file
        valid_links = 0
        for link in links:
            if link["url"]:
                file_content += f"({link['topic']}) {link['title']} : {link['url']}\n"
                valid_links += 1
        
        # Send as text file
        file_obj = io.BytesIO(file_content.encode('utf-8'))
        file_obj.name = filename
        
        await query.message.reply_document(
            document=file_obj,
            caption=f"✅ *{batch_name}*\n"
                   f"📊 Total Links: {valid_links}\n"
                   f"📁 Videos: {len([l for l in links if l['type'] == 'video'])}\n"
                   f"📄 PDFs: {len([l for l in links if l['type'] in ['pdf', 'study_pdf']])}\n\n"
                   f"🤖 Bot hosted on Render.com",
            parse_mode='Markdown'
        )
        
        await query.edit_message_text(f"✅ Extraction complete! Check above for the file.")
        
    except Exception as e:
        logger.error(f"Error in extraction: {e}")
        await query.edit_message_text(f"❌ Error: {str(e)[:100]}")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check bot status."""
    await update.message.reply_text(
        "✅ Bot is running!\n"
        "🔄 Status: Online\n"
        "☁️ Hosted on: Render.com\n"
        "📊 Use /batches to start"
    )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log errors."""
    logger.error(f"Update {update} caused error {context.error}")

def main():
    """Start the bot."""
    # Create Application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Register handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("batches", list_batches))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Error handler
    application.add_error_handler(error_handler)
    
    # Start the bot
    logger.info("🤖 Bot is starting on Render...")
    print("=" * 50)
    print("🚀 Telegram Bot Starting...")
    print(f"🤖 Bot Token: {'*' * len(BOT_TOKEN) if BOT_TOKEN else 'NOT SET'}")
    print("☁️ Host: Render.com")
    print("=" * 50)
    
    # Run bot with better error handling
    try:
        application.run_polling(
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES
        )
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
        raise

if __name__ == '__main__':
    main()
