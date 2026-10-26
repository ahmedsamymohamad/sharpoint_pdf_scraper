import os
import time
import base64
import re
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.common.exceptions import StaleElementReferenceException
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

# Try importing img2pdf for high-quality PDF compilation
try:
    import img2pdf
    HAS_IMG2PDF = True
except ImportError:
    HAS_IMG2PDF = False
    from PIL import Image

def scrape_sharepoint_pdf_to_single_pdf(url, output_filename):
    options = webdriver.ChromeOptions()
    
    # Use persistent profile to keep you logged in automatically
    profile_dir = os.path.join(os.getcwd(), "chrome_profile")
    options.add_argument(f"--user-data-dir={profile_dir}")
    
    service = Service()
    driver = webdriver.Chrome(service=service, options=options)
    
    try:
        print(f"▶️ Opening URL: {url}")
        driver.get(url)

        input(
            "\n🔐 Check the browser window. "
            "If SharePoint asks you to sign in, complete the login now. "
            "When the PDF page is ready (or login happened automatically), "
            "press Enter here to continue..."
        )
        
        print("⏳ Waiting for the SharePoint PDF viewer to load...")
        WebDriverWait(driver, 45).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "[class*='page_']"))
        )
        print("✅ PDF viewer loaded successfully!")
        
        # Brief pause to let all elements render
        time.sleep(5)
        
        saved_image_paths = []
        output_dir = os.path.join(os.getcwd(), "downloaded_pdf_pages")
        os.makedirs(output_dir, exist_ok=True)

        def capture_page(page_num, page_elem):
            print(f"Processing Page {page_num}...")
            file_path = os.path.join(output_dir, f"page_{page_num:03d}.png")

            try:
                driver.execute_script(
                    "arguments[0].scrollIntoView({block: 'center'});", page_elem
                )
                time.sleep(0.4)

                img = page_elem.find_element(By.TAG_NAME, "img")
                blob_url = img.get_attribute("src")

                if blob_url and blob_url.startswith("blob:"):
                    base64_data = driver.execute_async_script("""
                        const uri = arguments[0];
                        const callback = arguments[1];
                        fetch(uri)
                            .then(response => response.blob())
                            .then(blob => {
                                const reader = new FileReader();
                                reader.onloadend = () => callback(reader.result);
                                reader.readAsDataURL(blob);
                            })
                            .catch(err => callback(null));
                    """, blob_url)

                    if base64_data and "," in base64_data:
                        _, encoded = base64_data.split(",", 1)
                        with open(file_path, "wb") as fh:
                            fh.write(base64.decodebytes(encoded.encode("utf-8")))
                        if os.path.exists(file_path) and os.path.getsize(file_path) > 100:
                            saved_image_paths.append(file_path)
                            print(f"✅ Downloaded blob image for page {page_num}")
                            return True
            except Exception:
                pass

            try:
                page_elem.screenshot(file_path)
                if os.path.exists(file_path) and os.path.getsize(file_path) > 100:
                    saved_image_paths.append(file_path)
                    print(f"✅ Captured screenshot for page {page_num}")
                    return True
            except Exception as e:
                print(f"❌ Failed to capture page {page_num}: {e}")
            return False

        print("▶️ Locating and loading all page containers...")
        captured_page_numbers = set()
        stable_end_checks = 0
        previous_viewport = None

        # SharePoint virtualizes the viewer and initially renders only a few pages.
        # Scroll through the viewer while capturing each page as it is materialized.
        while stable_end_checks < 5:
            candidates = driver.find_elements(By.CSS_SELECTOR, "[class*='page_']")
            pages_captured_this_pass = 0

            for page_elem in candidates:
                try:
                    aria_label = page_elem.get_attribute("aria-label") or ""
                    class_name = page_elem.get_attribute("class") or ""
                except StaleElementReferenceException:
                    continue

                match = re.search(r'Page\s+(\d+)', aria_label, re.IGNORECASE)
                if not match:
                    match = re.search(r'page[_-](\d+)', class_name, re.IGNORECASE)
                if not match:
                    continue
                page_num = int(match.group(1))

                if page_num in captured_page_numbers:
                    continue

                try:
                    if capture_page(page_num, page_elem):
                        captured_page_numbers.add(page_num)
                        pages_captured_this_pass += 1
                except StaleElementReferenceException:
                    # The viewer may replace the element while it lazy-loads.
                    # It will be discovered again on the next pass.
                    continue

            candidates = driver.find_elements(By.CSS_SELECTOR, "[class*='page_']")
            if candidates:
                try:
                    driver.execute_script(
                        "arguments[0].scrollIntoView({block: 'end'});", candidates[-1]
                    )
                    driver.execute_script("window.scrollBy(0, 900);")
                    viewport = driver.execute_script("""
                        return [
                            window.scrollY,
                            document.documentElement.scrollHeight,
                            arguments[0].getBoundingClientRect().bottom
                        ];
                    """, candidates[-1])
                except StaleElementReferenceException:
                    viewport = None
                time.sleep(1.0)
            else:
                viewport = None

            if pages_captured_this_pass or viewport != previous_viewport:
                stable_end_checks = 0
            else:
                stable_end_checks += 1
            previous_viewport = viewport

        print(f"📄 Found {len(captured_page_numbers)} pages to process.")
        saved_image_paths.sort(
            key=lambda path: int(re.search(r"page_(\d+)\.png$", path).group(1))
        )

        if not saved_image_paths:
            print("❌ Failed to capture any pages.")
            return
        if not os.path.exists(os.getcwd()+"\\output_pdfs"):
            os.makedirs(os.getcwd()+"\\output_pdfs")

        # Compile captured pages into a single PDF
        final_pdf_path = os.path.join(os.getcwd()+"\\output_pdfs", f"{output_filename}.pdf")
        print(f"▶️ Compiling pages into final PDF: {final_pdf_path}")
        
        if HAS_IMG2PDF:
            with open(final_pdf_path, "wb") as f:
                f.write(img2pdf.convert(saved_image_paths))
        else:
            images = [Image.open(p).convert("RGB") for p in saved_image_paths]
            images[0].save(
                final_pdf_path,
                save_all=True,
                append_images=images[1:],
                resolution=100.0,
                quality=95
            )
            
        print(f"\n🎉 Success! Combined PDF saved to: {final_pdf_path}")

    finally:
        driver.quit()

if __name__ == "__main__":
    target_url_test = "https://xceedcceg.sharepoint.com/sites/Newuniversal/Shared%20Documents/Forms/AllItems.aspx?viewid=c721bea8%2D17ce%2D43f8%2Da2f7%2Ddbc7a3753082&id=%2Fsites%2FNewuniversal%2FShared%20Documents%2F01%2DTraining%20Material%20%2816%20WD%29%2FDay%2D09%20BLQ%2F06%2D%20BLQ%20%2Epdf&parent=%2Fsites%2FNewuniversal%2FShared%20Documents%2F01%2DTraining%20Material%20%2816%20WD%29%2FDay%2D09%20BLQ"
    target_url=input(f"▶️ Enter the URL of the SharePoint PDF to scrape: ")
    output_filename=input(f"▶️ Enter the desired output filename without extension (.pdf): ")
    scrape_sharepoint_pdf_to_single_pdf(target_url,output_filename)