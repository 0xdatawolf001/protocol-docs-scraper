import streamlit as st
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import pandas as pd
import time
import re
from st_copy_to_clipboard import st_copy_to_clipboard
import chardet
import fitz

@st.cache_data
def crawl_and_scrape(root_domain):
    visited_urls = set()
    queue = [root_domain]
    data = []
    failed_pages = []

    # Create placeholders for counter and current URL
    counter_placeholder = st.empty()
    url_placeholder = st.empty()

    counter = 0

    # Parse the root_domain to get the base and the path
    parsed_root = urlparse(root_domain)
    base_url = f"{parsed_root.scheme}://{parsed_root.netloc}"
    root_path = parsed_root.path.rstrip('/')

    # Create a regex pattern to match URLs that start with the base_url and contain the root_path
    url_pattern = re.compile(f"^{re.escape(base_url)}{re.escape(root_path)}(/|$)")

    df = pd.DataFrame(columns=["full_weblink", "main_body_text"])
    df.index.name = "index"

    while queue:
        url = queue.pop(0)
        if not url_pattern.match(url) or url in visited_urls:
            continue
        
        visited_urls.add(url)

        # Update counter and current URL
        counter += 1
        counter_placeholder.text(f"Pages processed: {counter}")
        url_placeholder.text(f"Current page: {url}")

        try:
            page_text = get_page_text(url)
            new_row = pd.DataFrame([[url, page_text]], columns=["full_weblink", "main_body_text"])
            df = pd.concat([df, new_row], ignore_index=True)
            df = df.drop_duplicates(subset='main_body_text', keep='first')

            soup = BeautifulSoup(requests.get(url).content, "html.parser")
            for link in soup.find_all("a", href=True):
                absolute_url = urljoin(url, link["href"])
                if url_pattern.match(absolute_url):
                    queue.append(absolute_url)

        except Exception as e:
            failed_pages.append(url)
            st.warning(f"Failed to process {url}: {str(e)}")

    return df, failed_pages

@st.cache_resource
def get_page_text(url):
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    
    content_type = response.headers.get('Content-Type', '').lower()
    
    if 'application/pdf' in content_type:
        # Handle PDF content
        pdf_content = response.content
        pdf_document = fitz.open(stream=pdf_content, filetype="pdf")
        text = ""
        for page in pdf_document:
            text += page.get_text()
        pdf_document.close()
        return text
    else:
        # Handle HTML content (existing code)
        detected_encoding = chardet.detect(response.content)['encoding']
        
        try:
            decoded_content = response.content.decode(detected_encoding or 'utf-8')
        except UnicodeDecodeError:
            decoded_content = response.content.decode('utf-8', errors='replace')
        
        soup = BeautifulSoup(decoded_content, "html.parser")
        for script in soup(["script", "style"]):
            script.extract()
        text = soup.get_text(" ", strip=True)
        return text

st.title("Protocol Documentation Scraper")
st.header("Scrape and consolidate protocol docs to feed into an LLM for faster understanding")
st.write("""
         Some use cases: 
         1) Ask questions
         2) Summarize
         3) Suggest data modeling and analytics
         4) Faster protocol understanding
         5) Critique protocol
         6) Competitor analysis

         https://aistudio.google.com, due to its high context window, is recommended as an LLM to paste large amount of text in 🙂
         """)

# Add toggle for text preview
show_preview = st.checkbox("Show text preview", value=False)

root_url = st.text_input("Enter Root Domain (e.g., https://docs.polymarket.com/)", "")

if 'df' not in st.session_state:
    st.session_state.df = None

if st.button("Scrape"):
    if root_url:
        with st.spinner("Crawling, scraping, and deduplicating..."):
            start_time = time.time()
            st.session_state.df, failed_pages = crawl_and_scrape(root_url)
            st.success("Crawling, scraping, and deduplication complete!")
            st.success(f"Total time: {time.time() - start_time:.2f} seconds")

if st.session_state.df is not None:
    st.write("### Scraped Data Table")
    st.write("First 20 results shown")
    st.dataframe(st.session_state.df.head(20).style.set_table_styles([{'selector': 'table', 'props': [('width', 'max-content'), ('overflow-x','auto')]}]))

    cleaned_url = re.sub(r'https?://', '', root_url).rstrip('/').replace('.', '_')
    file_name_csv = f"{cleaned_url}_{str(round(time.time()))}.csv"
    file_name_txt = f"{cleaned_url}_{str(round(time.time()))}.txt"
    
    csv = st.session_state.df.to_csv().encode('utf-8')
    st.download_button(
        label="Download Data as CSV",
        data=csv,
        file_name=file_name_csv,
        mime='text/csv',
    )

    all_text = "\n".join(st.session_state.df['main_body_text'])
    txt = all_text.encode('utf-8')
    st.download_button(
        label="Download Data as txt file",
        data=txt,
        file_name=file_name_txt,
        mime='text/plain',
    )

    if show_preview:
        st.text_area("Text to be copied:", all_text, height=150, key="copy_text")

    if st_copy_to_clipboard(all_text):
        st.success("Text copied to clipboard!")

    if 'failed_pages' in locals():
        if failed_pages:
            with st.expander("Failed Pages:"):
                st.warning("Some pages failed to scrape:")
                for url in failed_pages:
                    st.write(url)

else:
    st.warning("Please enter a root domain and click 'Scrape'.")