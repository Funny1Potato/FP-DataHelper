import openpyxl
import time
import sys
import json
import re
from pathlib import Path

from tqdm import tqdm


if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from method_support import (
    check_cancelled, process_workbook, report_output, run_script, save_workbook,
    should_append_columns, write_columns,
    find_header_row, worksheet_column, is_cas_header,
)


# ================= Selenium 抓取函数 =================
def init_driver():
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager

    options = webdriver.ChromeOptions()
    options.add_argument("--start-maximized")
    options.add_argument('--disable-gpu')
    options.add_argument('--no-sandbox')
    options.add_argument("--log-level=3")
    options.add_argument("--disable-notifications") 
    
    try:
        driver_path = ChromeDriverManager(url="https://npmmirror.com/metadata/chromedriver/").install()
    except Exception:
        driver_path = ChromeDriverManager().install()
        
    service = Service(driver_path)
    return webdriver.Chrome(service=service, options=options)

def get_chemicalbook_data_with_retry(driver, cas):
    """
    带有手动重试机制的抓取函数
    """
    while True:
        check_cancelled()
        try:
            return _get_data_logic(driver, cas)
        except Exception as e:
            check_cancelled()
            print("\n" + "!"*50)
            print(f"【暂停警告】在抓取 {cas} 时遇到问题！")
            print(f"错误信息: {e}")
            print("!"*50)
            
            try:
                user_input = input(">>> 请检查浏览器页面，恢复后按回车重试 (输入 n 跳过此条): ")
            except EOFError:
                check_cancelled()
                raise
            check_cancelled()
            
            if user_input.lower().strip() == 'n':
                print(f"已跳过 {cas}，香气属性留空。")
                return {
                    "CB_Odor_Desc": "\\", "CB_Odor_Threshold": "\\", "CB_Odor_Type": "\\"
                }
            else:
                print(">>> 正在重试...")
                continue

def check_page_status(driver):
    status = driver.execute_script(
        "return performance.getEntriesByType('navigation')[0]?.responseStatus"
    )
    if isinstance(status, int) and status >= 400:
        raise RuntimeError(f"ChemicalBook 返回 HTTP {status}。")


def _get_data_logic(driver, cas):
    """
    核心抓取逻辑（不含重试循环）
    """
    from selenium.common.exceptions import TimeoutException
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    data = {
        "CB_Odor_Desc": "\\",       
        "CB_Odor_Threshold": "\\",  
        "CB_Odor_Type": "\\"        
    }

    url = f"https://www.chemicalbook.com/Search.aspx?keyword={cas}"
    driver.get(url)
    check_page_status(driver)
    
    wait = WebDriverWait(driver, 5) 

    try:
        xpath_query = "//a[text()='化学性质' or contains(@href, 'ProductChemicalProperties')]"
        target_link = wait.until(EC.element_to_be_clickable((By.XPATH, xpath_query)))
        target_link.click()
    except TimeoutException as error:
        raise RuntimeError("页面没有显示「化学性质」入口。") from error

    windows = driver.window_handles
    driver.switch_to.window(windows[-1])
    check_page_status(driver)
    wait.until(EC.presence_of_element_located((By.TAG_NAME, "th")))

    try:
        ele = driver.find_element(By.XPATH, "//th[contains(text(), '气味')]/following-sibling::td")
        data["CB_Odor_Desc"] = ele.text.strip()
    except: pass

    try:
        ele = driver.find_element(By.XPATH, "//th[contains(text(), '嗅觉阈值')]/following-sibling::td")
        data["CB_Odor_Threshold"] = ele.text.strip()
    except: pass

    try:
        ele = driver.find_element(By.XPATH, "//th[contains(text(), '香型')]/following-sibling::td")
        data["CB_Odor_Type"] = ele.text.strip()
    except: pass

    if len(windows) > 1:
        driver.close()
        driver.switch_to.window(windows[0])

    return data

# ================= 处理单个工作表，添加“香气属性”列 =================
def process_sheet_add_odor(ws, cas_col_param, driver, show_progress=True):
    """为工作表计算香气属性列。"""
    cas_col = worksheet_column(ws, cas_col_param)
    header_idx = find_header_row(ws, is_cas_header, column=cas_col)
    rows = ws.iter_rows(min_row=header_idx + 1, values_only=True)
    headers = next(rows, ())
    if cas_col is None:
        cas_col = next((index for index, value in enumerate(headers) if is_cas_header(value)), None)
        if cas_col is None:
            raise ValueError("未找到CAS列，请通过参数1指定列字母。")
    data_rows = list(rows)

    # 收集所有唯一 CAS
    cas_set = set()
    for row in data_rows:
        if cas_col < len(row):
            val = row[cas_col]
            if val is not None and str(val).strip():
                cas_set.add(str(val).strip())

    # 查询香气属性（缓存）
    odor_cache = {}
    for cas in tqdm(cas_set, desc=f"查询 {ws.title} 香气属性", disable=not show_progress, unit="个"):
        result = get_chemicalbook_data_with_retry(driver, cas)
        # 合并三个字段为一个字符串
        parts = []
        if result["CB_Odor_Desc"] != "\\":
            parts.append(f"气味:{result['CB_Odor_Desc']}")
        if result["CB_Odor_Threshold"] != "\\":
            parts.append(f"阈值:{result['CB_Odor_Threshold']}")
        if result["CB_Odor_Type"] != "\\":
            parts.append(f"香型:{result['CB_Odor_Type']}")
        odor_cache[cas] = "; ".join(parts) if parts else "\\"
        time.sleep(1.5)   # 礼貌爬虫

    values = []
    for row in data_rows:
        cas_val = row[cas_col] if cas_col < len(row) else None
        if cas_val is None or str(cas_val).strip() == "":
            odor_val = ""
        else:
            odor_val = odor_cache.get(str(cas_val).strip(), "Not Found")
        values.append((odor_val,))

    return header_idx + 1, cas_col + 2, ("香气属性",), values


# ================= 主程序 =================
def main():
    option = json.loads(sys.argv[1])
    cas_col_param = option.get("Para1", "").strip()
    wb = openpyxl.load_workbook(option["File"])
    driver = None

    try:
        append = should_append_columns(wb)
        print("正在启动浏览器...")
        driver = init_driver()

        def process(ws):
            result = process_sheet_add_odor(ws, cas_col_param, driver)
            write_columns(ws, *result, append=append)

        process_workbook(wb, process)
        check_cancelled()
        out_path = save_workbook(wb, "_with_odor")
        print(f"处理完成，文件保存至：{out_path}")
        report_output(out_path)
    finally:
        wb.close()
        if driver is not None:
            driver.quit()


if __name__ == "__main__":
    sys.exit(run_script(main))
