FAT AutoFill Pro (v2.0)
=======================

이 패키지는 *새로운* GUI 프로그램입니다.
- MSBD PDF + GSP PDF + 템플릿 DOCX → 자동 추출 → DOCX 생성
- 추출 실패 시 화면에서 값 수정 후 바로 생성 가능

설치
----
1) Windows에서 이 폴더를 연 뒤 `install_win.bat` 실행 (가상환경 + 필수 패키지 설치)
2) 완료 후 `run_gui.bat` 실행

템플릿 준비
-----------
템플릿은 **docxtpl** 형식의 placeholder를 사용합니다. 다음 키를 포함해 주세요.

{{ customer }}, {{ hull_no }}, {{ owner }}, {{ class }}, {{ Kind_of_Vessel }}, {{ item }},
{{ ms_quantity }}, {{ ms_tr_capacity }}, {{ ms_fault_level }}, {{ ms_current }}, {{ ms_main_bus }},
{{ ms_munsell_code }}, {{ ms_ip }}, {{ ms_rating }}, {{ ms_dwg_no }}, {{ ms_rev_no }},
{{ gsp_paint }}, {{ gsp_ip }}, {{ gsp_quantity }}, {{ gsp_dwg_no }}, {{ gsp_rev_no }}

Function Test of GSP 항목을 사용하려면 다음 placeholder도 추가하세요.

{{ gsp_function_no1 }}, {{ gsp_function_no2 }}

동작 원리(요약)
----------------
- 표지(1p): REV(우선) → 실패 시 파일명 REV.M 폴백, DWG No., Hull No., CLASS 표(리스트/범위) 파싱
- GENERAL SPEC: SHORT CIRCUIT FAULT LEVEL(AC440/110 × rms/peak), OUTSIDE Munsell 코드, GSP 수량
- 텍스트 추출은 `pdfplumber`로 최대 20p까지 읽어 안정 처리

문제 해결
---------
- 템플릿 placeholder가 다를 경우, GUI의 "템플릿 진단"을 눌러 부족한 키를 확인하고 템플릿을 수정하세요.
- PDF 레이아웃이 달라 특정 항목이 비면, GUI에서 값을 직접 입력/수정 후 "보고서 생성"하세요.
