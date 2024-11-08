import streamlit as st
import git
import os
import tempfile
import json
from io import BytesIO
from st_copy_to_clipboard import st_copy_to_clipboard


# Cache the function to preserve data across reruns
@st.cache_data
def clone_repo(repo_url, temp_dir):
    try:
        git.Repo.clone_from(repo_url, temp_dir)
        return True
    except git.GitCommandError:
        return False


# Cache the function to preserve data across reruns
@st.cache_data
def extract_files(temp_dir, file_types):
    extracted_content = {}
    for root, dirs, files in os.walk(temp_dir):
        for file in files:
            file_path = os.path.join(root, file)
            relative_path = os.path.relpath(file_path, temp_dir)

            # Check if the file matches the selected types
            if (
                ("md" in file_types and file.endswith(".md"))
                or ("sol" in file_types and file.endswith(".sol"))
                or (
                    "json" in file_types
                    and file.endswith(".json")
                    and "artifacts" in relative_path.split(os.sep)
                )
            ):
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    extracted_content[relative_path] = f.read()
    return extracted_content


# Function to get a snippet of text
def get_snippet(text, max_length=500):
    if len(text) <= max_length:
        return text
    return text[:max_length] + "..."


st.title("GitHub Repository Extractor")
st.subheader(
    "Put the entire code base in one file for easier/faster copy and pasting to LLMs"
)

st.write("""
         Enter GitHub repository URLs (one per line):
         
         www.example.com
         
         www.example2.com
         ...
         """)
repo_urls = st.text_area("GitHub URLs")

# Add file type selection
file_types = st.multiselect(
    "Select file types to scrape (default is all):",
    ["md", "sol", "json"],
    default=["md", "sol", "json"],
)

# Add this near the top of your script, after the imports
if "previous_repo_urls" not in st.session_state:
    st.session_state.previous_repo_urls = ""

# Add this right after the repo_urls text_area
if repo_urls != st.session_state.previous_repo_urls:
    st.cache_data.clear()
    st.session_state.all_extracted_content = {}
    st.session_state.previous_repo_urls = repo_urls

# Use session state to preserve data across reruns
if "all_extracted_content" not in st.session_state:
    st.session_state.all_extracted_content = {}

if st.button("Process Repositories"):
    repo_list = repo_urls.split("\n")
    progress_bar = st.progress(0)
    status_text = st.empty()

    for i, repo_url in enumerate(repo_list):
        repo_url = repo_url.strip()
        if repo_url:
            with tempfile.TemporaryDirectory() as temp_dir:
                status_text.text(f"Scraping {repo_url} ({i+1}/{len(repo_list)})")
                if clone_repo(repo_url, temp_dir):
                    extracted_content = extract_files(temp_dir, file_types)
                    repo_name = repo_url.split("/")[-1].replace(".git", "")
                    st.session_state.all_extracted_content[repo_name] = (
                        extracted_content
                    )
                else:
                    st.error(f"Failed to clone: {repo_url}")
        progress_bar.progress((i + 1) / len(repo_list))

    status_text.text("All repositories processed!")

if st.session_state.all_extracted_content:
    st.subheader("Extracted Content")
    with st.spinner("Processing content..."):
        text_content = ""
        display_content = ""
        repo_names = list(st.session_state.all_extracted_content.keys())

        for repo, files in st.session_state.all_extracted_content.items():
            text_content += f"\n\n{'=' * 20} {repo} {'=' * 20}\n\n"
            display_content += f"\n\n{'=' * 20} {repo} {'=' * 20}\n\n"
            for file_path, content in files.items():
                text_content += f"\n\n{'=' * 20} {file_path} {'=' * 20}\n\n"
                text_content += content
                display_content += f"\n\n{'=' * 20} {file_path} {'=' * 20}\n\n"
                display_content += get_snippet(content)

        # Generate file names based on the number of repos
        if len(repo_names) == 1:
            file_name = repo_names[0]
        else:
            file_name = "_".join(repo_names)

        # Download as text file
        text_file = BytesIO(text_content.encode())
        st.download_button(
            label="Download as Text File",
            data=text_file,
            file_name=f"{file_name}.txt",
            mime="text/plain",
        )

        # Download as JSON
        json_content = json.dumps(
            {
                repo: {file_path: content for file_path, content in files.items()}
                for repo, files in st.session_state.all_extracted_content.items()
            },
            indent=2,
        )
        json_file = BytesIO(json_content.encode())
        st.download_button(
            label="Download as JSON",
            data=json_file,
            file_name=f"{file_name}.json",
            mime="application/json",
        )

        # Copy to clipboard
        if st_copy_to_clipboard(text_content):
            try:
                st.success("Text copied to clipboard!")
            except Exception as e:
                st.error(
                    "The text is too large to copy to clipboard. Please download the text file instead."
                )
                st.info(
                    "Click the 'Download as Text File' button above to save the content."
                )

        # Display snippet
        st.write(f"""The text content is {len(text_content)} words long""")
        st.text_area(
            "Content preview (snippet)", display_content, height=300, disabled=True
        )

st.write(
    "Note that if your text is huge you will get an Error and I would recommend that you download the text file instead"
)
