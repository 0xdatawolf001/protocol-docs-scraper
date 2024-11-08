import streamlit as st
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, urlunparse
import pandas as pd
import time
import re
from st_copy_to_clipboard import st_copy_to_clipboard
import chardet
import fitz
import json
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor

# Add this near the top of the script
IGNORED_SUFFIXES = [
    ".rst",
    ".png",
    ".gif",
    ".jpeg",
    ".jpg",
]  # Add more suffixes here as needed


@st.cache_data
def crawl_and_scrape(root_domain, max_depth=5, max_consecutive_backtrack=20):
    visited_urls = set()
    queue = [(root_domain, [root_domain], 0)]  # (url, breadcrumb, depth)
    data = []
    failed_pages = []

    # Create placeholders for counter and current URL
    counter_placeholder = st.empty()
    url_placeholder = st.empty()
    counter = 0

    # Parse the root_domain to get the base and the path
    parsed_root = urlparse(root_domain)
    base_url = f"{parsed_root.scheme}://{parsed_root.netloc}"
    root_path = parsed_root.path.rstrip("/")

    # Create a regex pattern to match URLs that start with the base_url and contain the root_path
    url_pattern = re.compile(f"^{re.escape(base_url)}{re.escape(root_path)}(/|$)")

    def normalize_url(url):
        parsed = urlparse(url)
        path = parsed.path.split("/")
        normalized_path = []
        for segment in path:
            if segment == "." or segment == "":
                continue
            if segment == "..":
                if normalized_path:
                    normalized_path.pop()
            else:
                normalized_path.append(segment)
        normalized_url = urlunparse(
            (
                parsed.scheme,
                parsed.netloc,
                "/".join(normalized_path),
                parsed.params,
                parsed.query,
                "",
            )
        )
        return normalized_url

    consecutive_backtrack = 0
    while queue:
        url, breadcrumb, depth = queue.pop(0)

        # Normalize the URL
        url = normalize_url(url)

        # Parse the URL
        parsed_url = urlparse(url)

        # Remove the fragment from the URL
        url_without_fragment = parsed_url._replace(fragment="").geturl()

        # Check if the URL should be ignored based on its suffix
        if any(url_without_fragment.endswith(suffix) for suffix in IGNORED_SUFFIXES):
            continue

        if (
            not url_pattern.match(url_without_fragment)
            or url_without_fragment in visited_urls
        ):
            continue

        visited_urls.add(url_without_fragment)

        # Update counter and current URL
        counter += 1
        counter_placeholder.text(f"Pages crawled: {counter}")
        url_placeholder.text(f"Current page: {url_without_fragment}")

        try:
            response = requests.get(url_without_fragment, timeout=10)
            soup = BeautifulSoup(response.content, "html.parser")

            # Only process links if we haven't reached the maximum depth
            if depth < max_depth:
                new_links = []
                for link in soup.find_all("a", href=True):
                    absolute_url = urljoin(url_without_fragment, link["href"])
                    absolute_url = normalize_url(absolute_url)
                    parsed_absolute_url = urlparse(absolute_url)
                    absolute_url_without_fragment = parsed_absolute_url._replace(
                        fragment=""
                    ).geturl()

                    if url_pattern.match(absolute_url_without_fragment) and not any(
                        absolute_url_without_fragment.endswith(suffix)
                        for suffix in IGNORED_SUFFIXES
                    ):
                        new_breadcrumb = breadcrumb + [absolute_url_without_fragment]
                        new_links.append(
                            (absolute_url_without_fragment, new_breadcrumb, depth + 1)
                        )

                if new_links:
                    queue.extend(new_links)
                    consecutive_backtrack = 0
                else:
                    # If no new links, backtrack
                    consecutive_backtrack += 1
                    if consecutive_backtrack > max_consecutive_backtrack:
                        # Aggressive backtracking
                        while (
                            breadcrumb and len(breadcrumb) > 1
                        ):  # Ensure we don't go beyond root
                            breadcrumb.pop()
                            depth -= 1
                            if breadcrumb[-1] not in visited_urls:
                                queue.insert(
                                    0, (breadcrumb[-1], breadcrumb.copy(), depth)
                                )
                                consecutive_backtrack = 0
                                break
                    else:
                        # Normal backtracking
                        if breadcrumb:
                            breadcrumb.pop()
                            depth -= 1
                            if breadcrumb:
                                queue.insert(
                                    0, (breadcrumb[-1], breadcrumb.copy(), depth)
                                )

        except requests.RequestException as e:
            failed_pages.append(url_without_fragment)
            st.warning(f"Failed to crawl {url_without_fragment}: {str(e)}")

    # Scraping with concurrency
    def scrape_url(url):
        try:
            page_text = get_page_text(url)
            return url, page_text
        except Exception as e:
            failed_pages.append(url)
            st.warning(f"Failed to scrape {url}: {str(e)}")
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        future_to_url = {executor.submit(scrape_url, url): url for url in visited_urls}
        for future in concurrent.futures.as_completed(future_to_url):
            result = future.result()
            if result:
                data.append(result)

    # Create DataFrame and deduplicate
    df = pd.DataFrame(data, columns=["full_weblink", "main_body_text"])
    df = df.drop_duplicates(subset="main_body_text", keep="first")
    df.index.name = "index"

    return df, failed_pages


@st.cache_resource
def get_page_text(url):
    response = requests.get(url, timeout=10)
    response.raise_for_status()

    content_type = response.headers.get("Content-Type", "").lower()

    if "application/pdf" in content_type:
        if scrape_pdfs:
            # Handle PDF content
            pdf_content = response.content
            pdf_document = fitz.open(stream=pdf_content, filetype="pdf")
            text = ""
            for page in pdf_document:
                text += page.get_text()
            pdf_document.close()
            return text
        else:
            return "PDF content skipped as per user preference."
    else:
        # Handle HTML content (existing code)
        detected_encoding = chardet.detect(response.content)["encoding"]

        try:
            decoded_content = response.content.decode(detected_encoding or "utf-8")
        except UnicodeDecodeError:
            decoded_content = response.content.decode("utf-8", errors="replace")

        soup = BeautifulSoup(decoded_content, "html.parser")
        for script in soup(["script", "style"]):
            script.extract()
        text = soup.get_text(" ", strip=True)
        return text


st.title("Protocol Documentation Scraper")
st.header(
    "Scrape and consolidate protocol docs to feed into an LLM for faster understanding"
)
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

# Create two columns for checkboxes
col1, col2 = st.columns(2)

# Add toggle for text preview in the first column
with col1:
    show_preview = st.checkbox("Show text preview", value=False)

# Add toggle for PDF scraping in the second column
with col2:
    scrape_pdfs = st.checkbox("Scrape PDFs", value=True)

root_url = st.text_input("Enter Root Domain (e.g., https://docs.polymarket.com/)", "")

if "df" not in st.session_state:
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
    st.dataframe(
        st.session_state.df.head(20).style.set_table_styles(
            [
                {
                    "selector": "table",
                    "props": [("width", "max-content"), ("overflow-x", "auto")],
                }
            ]
        )
    )

    cleaned_url = re.sub(r"https?://", "", root_url).rstrip("/").replace(".", "_")
    file_name_csv = f"{cleaned_url}_{str(round(time.time()))}.csv"
    file_name_txt = f"{cleaned_url}_{str(round(time.time()))}.txt"
    file_name_json = f"{cleaned_url}_{str(round(time.time()))}.json"

    csv = st.session_state.df.to_csv().encode("utf-8")
    st.download_button(
        label="Download Data as CSV",
        data=csv,
        file_name=file_name_csv,
        mime="text/csv",
    )

    all_text = "\n".join(st.session_state.df["main_body_text"])
    txt = all_text.encode("utf-8")
    st.download_button(
        label="Download Data as txt file",
        data=txt,
        file_name=file_name_txt,
        mime="text/plain",
    )

    # New button for JSON download
    json_data = st.session_state.df.set_index("full_weblink")[
        "main_body_text"
    ].to_dict()
    json_str = json.dumps(json_data, ensure_ascii=False, indent=2)
    st.download_button(
        label="Download Data as JSON",
        data=json_str,
        file_name=file_name_json,
        mime="application/json",
    )

    if show_preview:
        st.text_area("Text to be copied:", all_text, height=150, key="copy_text")

    if st_copy_to_clipboard(all_text):
        st.success("Text copied to clipboard!")

    if "failed_pages" in locals():
        if failed_pages:
            with st.expander("Failed Pages:"):
                st.warning("Some pages failed to scrape:")
                for url in failed_pages:
                    st.write(url)

else:
    st.warning("Please enter a root domain and click 'Scrape'.")
