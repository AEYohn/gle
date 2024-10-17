import streamlit as st
import pandas as pd
import os
import requests
from bs4 import BeautifulSoup
import json
import re
from datetime import datetime, timedelta
from io import BytesIO
from requests.exceptions import RequestException

# Set up Streamlit configuration
st.set_page_config(page_title="Court Session Notes", layout="wide")

# Streamlit title
st.title("Court Session Notes")

# Date selector
selected_date = st.date_input("Select a date", datetime.today())

# Generate filename based on selected date
date_str = selected_date.strftime('%Y-%m-%d')
filename = f'assignments_{date_str}.csv'

# Constants and patterns
time_pattern = r'\b(\d{1,2}:\d{2} [AP]M)\b'
courts = ['4A','4B','7A','7B','8A', '10A', '10B', '10C', '10D', '11A', '11B', '11C', '11D', '13A', '13B', '13C',
          '13D', '15A', '15B', '15C', '18A', '18B', '18C', '19A', '19B', '19C', '19D', '24A',
          '24B', '24C', '24D', '29A', '29B', '29C', '29D', '30A', '30B', '30C', '30D',
          '32A', '32B', '32C', '32D']

# Functions for data extraction and processing
def extract_accused_name(soup):
    accused_tags = soup.find_all('h4')
    accused_names = [tag.text.strip() for tag in accused_tags if "v." in tag.text]
    return accused_names

def extract_name(accused_str):
    match = re.search(r'v\.\s*(.+)', accused_str)
    return match.group(1).strip() if match else accused_str

def fetch_court_data(court, start, end):
    url = 'https://www.judiciary.gov.sg/hearing-list/GetFilteredList/'
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "*/*",
        "X-Requested-With": "XMLHttpRequest"
    }
    body = {
        "SearchKeywords": court,
        "SelectedStartDate": start,
        "SelectedEndDate": end,
        "SelectedPageSize": "100",
        "SelectedSortBy": "0"
    }
    try:
        response = requests.post(url, headers=headers, json=body, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data
    except RequestException as e:
        st.error(f"Network error occurred while fetching data for court {court}: {e}")
        return None
    except json.JSONDecodeError:
        st.error(f"Failed to decode JSON response for court {court}")
        return None

def process_court_data(court, data, df):
    soup = BeautifulSoup(str(data), 'html.parser')
    hearing_type_tags = soup.find_all('div', class_='hearing-type')
    times = [re.search(time_pattern, tag).group(1) for tag in soup.find_all(string=re.compile(time_pattern)) if re.search(time_pattern, tag)]
    hearings = [tag.text.strip() for tag in hearing_type_tags]
    accused_names = extract_accused_name(soup)

    min_length = min(len(times), len(hearings), len(accused_names))
    for i in range(min_length):
        accused = extract_name(accused_names[i]) if i < len(accused_names) else "Unknown"
        df = pd.concat([df, pd.DataFrame({
            'Court': [court],
            'Time': [times[i]],
            'Hearing Type': [hearings[i]],
            'Accused': [accused]
        })], ignore_index=True)
    return df

def group_data(df_period):
    grouped = df_period.groupby('Court').agg(
        M_Count=('Indicator', lambda x: (x == 'M').sum()),
        H_Count=('Indicator', lambda x: (x == 'H').sum()),
        Unknown_Count=('Indicator', lambda x: (x == 'U').sum()),
        Time=('Time', ', '.join),
        Hearing_Type=('Hearing Type', ', '.join),
        Accused=('Accused', ', '.join)
    ).reset_index()

    # Create the Label column
    def create_label(row):
        labels = []
        if row['M_Count'] > 0:
            labels.append(f"{row['M_Count']}M")
        if row['H_Count'] > 0:
            labels.append(f"{row['H_Count']}H")
        if row['Unknown_Count'] > 0:
            labels.append(f"{row['Unknown_Count']}?")
        return ' '.join(labels)

    grouped['Label'] = grouped.apply(create_label, axis=1)
    return grouped

# Main data fetching and processing
def fetch_and_process_data():
    df = pd.DataFrame(columns=['Court', 'Time', 'Hearing Type', 'Accused'])
    end = f"{selected_date.strftime('%Y-%m-%d')}T15:59:00.000Z"
    start = f"{(selected_date - timedelta(1)).strftime('%Y-%m-%d')}T16:00:00.000Z"

    for court in courts:
        data = fetch_court_data(court, start, end)
        if data:
            df = process_court_data(court, data, df)

    if df.empty:
        st.warning("No data fetched for the selected date.")
        return pd.DataFrame(), pd.DataFrame()

    # Adding the 'Indicator' column based on the hearing type
    def assign_indicator(hearing_type):
        if 'Mention' in hearing_type:
            return 'M'
        elif 'Trial' in hearing_type or 'Heard' in hearing_type or 'Hearing' in hearing_type:
            return 'H'
        else:
            return 'U'  # Unknown

    df['Indicator'] = df['Hearing Type'].apply(assign_indicator)

    # Convert 'Time' to datetime
    df['Time_dt'] = pd.to_datetime(df['Time'], format='%I:%M %p')

    # Split data based on 12:30 PM
    split_time = datetime.strptime('12:30 PM', '%I:%M %p').time()

    df_am = df[df['Time_dt'].dt.time < split_time].reset_index(drop=True)
    df_pm = df[df['Time_dt'].dt.time >= split_time].reset_index(drop=True)

    grouped_am = group_data(df_am)
    grouped_pm = group_data(df_pm)

    return grouped_am, grouped_pm

# Fetch and process data
grouped_am, grouped_pm = fetch_and_process_data()

# Prepare the assignments DataFrame
columns = ['Court', 'AM M/H', 'PM M/H']
df_template_simple = pd.DataFrame(columns=columns)

for court in courts:
    am_label = grouped_am.loc[grouped_am['Court'] == court, 'Label'].values[0] if court in grouped_am['Court'].values else ""
    pm_label = grouped_pm.loc[grouped_pm['Court'] == court, 'Label'].values[0] if court in grouped_pm['Court'].values else ""

    df_template_simple = pd.concat([df_template_simple, pd.DataFrame({
        'Court': [court],
        'AM M/H': [am_label],
        'PM M/H': [pm_label]
    })], ignore_index=True)

# Add columns for remarks and ended status
df_template_simple['Remarks'] = ""
df_template_simple['Ended'] = False

total_courts = df_template_simple[
    (df_template_simple['AM M/H'] != "") | (df_template_simple['PM M/H'] != "")
].shape[0]

# 1. Display Court Status first
st.header("Court Status")

# Filter the DataFrame to only include courts with non-empty 'AM M/H' or 'PM M/H'
df_court_status = df_template_simple.copy()
df_court_status = df_court_status[
    (df_court_status['AM M/H'] != "") | (df_court_status['PM M/H'] != "")
].reset_index(drop=True)

# Highlight the rows where the court has ended
def highlight_ended_rows(row):
    return ['background-color: lightgreen'] * len(row) if row['Ended'] else [''] * len(row)

# Display the filtered DataFrame
st.dataframe(
    df_court_status.style.apply(highlight_ended_rows, axis=1),
    use_container_width=True
)

# 2. Display Total Courts
st.header(f"Total Courts: {total_courts}")

# 3. Display Grouped AM Data (Include 'Time' and 'Hearing Type')
st.header("Grouped AM Data")
if not grouped_am.empty:
    st.dataframe(
        grouped_am[['Court', 'Label', 'Time', 'Hearing_Type', 'Accused']].style.hide(axis="index"),
        use_container_width=True
    )
else:
    st.write("No grouped AM data available.")

# 4. Include AM 'H' Courts, PM 'H' Courts, and PM 'M' Courts in PM Data

# Extract PM 'H' and 'M' courts
pm_courts = grouped_pm[(grouped_pm['H_Count'] > 0) | (grouped_pm['M_Count'] > 0) | (grouped_pm['Unknown_Count'] > 0)][['Court', 'Label', 'Time', 'Hearing_Type', 'Accused']]

# Extract AM 'H' courts
am_h_courts = grouped_am[(grouped_am['H_Count'] > 0) | (grouped_am['Unknown_Count'] > 0)][['Court', 'Label', 'Time', 'Hearing_Type', 'Accused']]

# Combine PM 'H' and 'M' courts with AM 'H' courts
combined_pm_courts = pd.concat([pm_courts, am_h_courts], ignore_index=True)
combined_pm_courts = combined_pm_courts.drop_duplicates(subset='Court').reset_index(drop=True)

# Initialize 'Remove' column
combined_pm_courts['Remove'] = False

# Provide interface to remove courts
st.header("Grouped PM Data (Including AM 'H' Courts and PM 'H' and 'M' Courts)")

# Create a form to display and update remove status
with st.form(key='remove_form'):
    # Display the combined PM courts with checkboxes to remove
    for idx, row in combined_pm_courts.iterrows():
        court = row['Court']
        label = row['Label']
        time = row['Time']
        hearing_type = row['Hearing_Type']
        accused = row['Accused']
        remove = st.checkbox(f"Remove Court {court} - {label} - Time: {time} - Hearing Type: {hearing_type} - Accused: {accused}", value=row['Remove'])
        combined_pm_courts.at[idx, 'Remove'] = remove

    # Submit button to update remove status
    submitted = st.form_submit_button("Update PM Courts")
    if submitted:
        st.success("PM courts updated.")

# Filter out removed courts
display_pm_courts = combined_pm_courts[~combined_pm_courts['Remove']]

# Highlight removed courts in the display
def highlight_removed_rows(row):
    return ['background-color: lightgray'] * len(row) if row['Remove'] else [''] * len(row)

# Display the combined PM courts with remove status (Include 'Time' and 'Hearing Type')
st.dataframe(
    combined_pm_courts[['Court', 'Label', 'Time', 'Hearing_Type', 'Accused', 'Remove']].style.apply(highlight_removed_rows, axis=1),
    use_container_width=True
)

# 5. Display the assignments with editable functionality
st.header("Edit Remarks")

# Define column configuration
column_config = {
    'AM M/H': st.column_config.TextColumn(
        'AM M/H',
        help='Edit AM M/H',
        width='small',
    ),
    'PM M/H': st.column_config.TextColumn(
        'PM M/H',
        help='Edit PM M/H',
        width='small',
    ),
    'Remarks': st.column_config.TextColumn(
        'Remarks',
        help='Enter any remarks or notes for the court session',
        width='large',
    ),
    'Ended': st.column_config.CheckboxColumn(
        'Ended',
        help='Indicate if the court session has ended',
        width='small',
    ),
}

# Display the data editor
edited_assignments = st.data_editor(
    df_template_simple,
    column_config=column_config,
    hide_index=True,
    use_container_width=True,
    num_rows='dynamic',
    key='data_editor'
)

# Update the assignments DataFrame
df_template_simple = edited_assignments

# After editing, update the Court Status
df_court_status = df_template_simple[
    (df_template_simple['AM M/H'] != "") | (df_template_simple['PM M/H'] != "")
].reset_index(drop=True)

# Display the updated Court Status
st.header("Updated Court Status")

st.dataframe(
    df_court_status.style.apply(highlight_ended_rows, axis=1),
    use_container_width=True
)

# 6. Display the general remarks text area
st.header("General Remarks")
general_remarks = st.text_area(
    "Enter your general remarks or notes here:",
    value="",
    height=150
)

# 7. Others (e.g., Export Functionality)

# Export Functionality
st.header("Export Data to Excel")

# Get the list of columns from the DataFrame
all_columns = list(df_template_simple.columns)

# Let the user select columns to export
selected_columns = st.multiselect(
    "Select columns to export",
    options=all_columns + ['General Remarks'],  # Include 'General Remarks' as an option
    default=all_columns  # Default to all columns selected
)

# Button to export data
if st.button("Export to Excel"):
    # Create a BytesIO buffer
    output = BytesIO()
    # Write the DataFrame to the buffer
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        # Prepare the DataFrame for export
        export_df = df_template_simple[selected_columns].copy()
        # If 'General Remarks' is selected, add it to the DataFrame
        if 'General Remarks' in selected_columns:
            export_df['General Remarks'] = general_remarks
        export_df.to_excel(writer, index=False, sheet_name='Court Data')
        # Export PM courts with remove status
        pm_courts_export = combined_pm_courts[['Court', 'Label', 'Time', 'Hearing_Type', 'Accused', 'Remove']]
        pm_courts_export.to_excel(writer, index=False, sheet_name='PM Courts')
    # Set the buffer position to the beginning
    output.seek(0)
    # Create a download button
    st.download_button(
        label="Download Excel File",
        data=output,
        file_name=f"Court_Session_Notes_{date_str}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
