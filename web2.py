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
import psycopg2
from psycopg2 import sql

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
courts = ['4A', '4B', '7A', '7B', '8A', '10A', '10B', '10C', '10D', '11A', '11B', '11C', '11D',
          '13A', '13B', '13C', '13D', '15A', '15B', '15C', '18A', '18B', '18C', '19A', '19B',
          '19C', '19D', '24A', '24B', '24C', '24D', '29A', '29B', '29C', '29D', '30A', '30B',
          '30C', '30D', '32A', '32B', '32C', '32D']

# Database credentials
DB_NAME = "court_system"
DB_USER = "postgres"
DB_PASSWORD = "Asdf345jkl"  # Replace with your actual password or use environment variables
DB_HOST = "localhost"
DB_PORT = "5433"

# Establish a connection
try:
    conn = psycopg2.connect(
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=DB_PORT
    )
    cursor = conn.cursor()
    st.success("Connected to the database successfully.")
except Exception as e:
    st.error(f"Error connecting to the database: {e}")

# Create tables if they don't exist
def create_tables():
    create_courts_table = '''
    CREATE TABLE IF NOT EXISTS Courts (
        ID SERIAL PRIMARY KEY,
        CourtName VARCHAR(50) NOT NULL UNIQUE
    );
    '''
    
    create_hearings_table = '''
    CREATE TABLE IF NOT EXISTS Hearings (
        HearingID SERIAL PRIMARY KEY,
        CourtID INT,
        StartTime TIMESTAMP NOT NULL,
        EndTime TIMESTAMP,
        HearingType VARCHAR(50) NOT NULL,
        Status VARCHAR(20) NOT NULL DEFAULT 'Scheduled',
        FOREIGN KEY (CourtID) REFERENCES Courts(ID)
    );
    '''
    
    create_accused_table = '''
    CREATE TABLE IF NOT EXISTS Accused (
        AccusedID SERIAL PRIMARY KEY,
        Name VARCHAR(100) NOT NULL,
        CaseNumber VARCHAR(50)
    );
    '''
    
    create_assignments_table = '''
    CREATE TABLE IF NOT EXISTS Assignments (
        AssignmentID SERIAL PRIMARY KEY,
        Court VARCHAR(10) NOT NULL UNIQUE,
        AM_MH VARCHAR(10),
        PM_MH VARCHAR(10),
        Remarks TEXT,
        Ended BOOLEAN DEFAULT FALSE
    );
    '''
    
    create_groupeddata_table = '''
    CREATE TABLE IF NOT EXISTS GroupedData (
        GroupID SERIAL PRIMARY KEY,
        Court VARCHAR(10) NOT NULL,
        Session VARCHAR(2) NOT NULL, -- 'AM' or 'PM'
        Label VARCHAR(20),
        Time TEXT,
        HearingType TEXT,
        Accused TEXT,
        UNIQUE (Court, Session)
    );
    '''
    
    create_pmcourts_table = '''
    CREATE TABLE IF NOT EXISTS PMCourts (
        PMCourtID SERIAL PRIMARY KEY,
        Court VARCHAR(10) NOT NULL UNIQUE,
        Label VARCHAR(20),
        Time TEXT,
        HearingType TEXT,
        Accused TEXT,
        Remove BOOLEAN DEFAULT FALSE
    );
    '''
    
    create_remarks_table = '''
    CREATE TABLE IF NOT EXISTS Remarks (
        RemarkID SERIAL PRIMARY KEY,
        Date DATE NOT NULL UNIQUE,
        Content TEXT
    );
    '''
    
    create_court_data_table = '''
    CREATE TABLE IF NOT EXISTS court_data (
        id SERIAL PRIMARY KEY,
        date DATE NOT NULL,
        court VARCHAR(10) NOT NULL,
        time VARCHAR(10),
        hearing_type TEXT,
        accused TEXT,
        indicator VARCHAR(1),
        last_updated TIMESTAMP NOT NULL,
        UNIQUE (date, court, time, hearing_type, accused)
    );
    '''
    
    create_court_status_table = '''
    CREATE TABLE IF NOT EXISTS court_status (
        id SERIAL PRIMARY KEY,
        date DATE NOT NULL,
        court VARCHAR(10) NOT NULL,
        session VARCHAR(2) NOT NULL,
        mh_label VARCHAR(20),
        remarks TEXT,
        officers_deployed TEXT,
        court_start BOOLEAN,
        court_start_time TIME,
        court_end BOOLEAN,
        court_end_time TIME,
        last_updated TIMESTAMP NOT NULL,
        UNIQUE (date, court, session)
    );
    '''
    
    create_officers_table = '''
    CREATE TABLE IF NOT EXISTS Officers (
        OfficerID SERIAL PRIMARY KEY,
        OfficerName VARCHAR(100) NOT NULL UNIQUE,
        Team VARCHAR(10),
        Intake INT,
        Status VARCHAR(10) CHECK (Status IN ('Regular', 'SC', 'Freshie')),
        Availability VARCHAR(15) CHECK (Availability IN ('Available', 'Non Available')),
        TimeSensitive BOOLEAN NOT NULL DEFAULT FALSE
    );
    '''
    
    cursor.execute(create_courts_table)
    cursor.execute(create_hearings_table)
    cursor.execute(create_accused_table)
    cursor.execute(create_assignments_table)
    cursor.execute(create_groupeddata_table)
    cursor.execute(create_pmcourts_table)
    cursor.execute(create_remarks_table)
    cursor.execute(create_court_data_table)
    cursor.execute(create_court_status_table)
    cursor.execute(create_officers_table)
    conn.commit()

create_tables()

# Function to check if data exists in the database and is recent
def get_data_from_db(selected_date):
    query = '''
    SELECT * FROM court_data WHERE date = %s AND last_updated >= NOW() - INTERVAL '30 minutes';
    '''
    cursor.execute(query, (selected_date,))
    rows = cursor.fetchall()
    return rows

# Function to fetch and process data
def fetch_and_process_data():
    data_rows = get_data_from_db(selected_date)
    if data_rows:
        # Load data from database into DataFrame df
        df = pd.DataFrame(data_rows, columns=['id', 'date', 'Court', 'Time', 'Hearing Type', 'Accused', 'Indicator', 'last_updated'])
        # Drop 'id', 'date', 'last_updated' columns
        df = df.drop(columns=['id', 'date', 'last_updated'])
        st.info("Loaded data from the database.")
    else:
        # Proceed to fetch data from the web
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

        # Store data into the database
        try:
            for index, row in df.iterrows():
                insert_query = '''
                INSERT INTO court_data (date, court, time, hearing_type, accused, indicator, last_updated)
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (date, court, time, hearing_type, accused) DO UPDATE SET
                    indicator = EXCLUDED.indicator,
                    last_updated = NOW();
                '''
                cursor.execute(insert_query, (selected_date, row['Court'], row['Time'], row['Hearing Type'], row['Accused'], row['Indicator']))
            conn.commit()
            st.info("Data fetched from web and stored in the database.")
        except Exception as e:
            conn.rollback()
            st.error(f"Error inserting data into database: {e}")

    # Convert 'Time' to datetime
    df['Time_dt'] = pd.to_datetime(df['Time'], format='%I:%M %p')

    # Split data based on 12:30 PM
    split_time = datetime.strptime('12:30 PM', '%I:%M %p').time()

    df_am = df[df['Time_dt'].dt.time < split_time].reset_index(drop=True)
    df_pm = df[df['Time_dt'].dt.time >= split_time].reset_index(drop=True)

    grouped_am = group_data(df_am)
    grouped_pm = group_data(df_pm)

    return grouped_am, grouped_pm

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
        "Accept": "/",
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

# Fetch and process data
grouped_am, grouped_pm = fetch_and_process_data()

# Prepare the assignments DataFrame with separate AM and PM sessions
columns = ['Court', 'Session', 'M/H Label', 'Remarks', 'Officers Deployed', 'Court Start', 'Court Start Time', 'Court End', 'Court End Time']
data_list = []

# Create rows for AM sessions
for index, row in grouped_am.iterrows():
    data_list.append({
        'Court': row['Court'],
        'Session': 'AM',
        'M/H Label': row['Label'],
        'Remarks': '',
        'Officers Deployed': '',
        'Court Start': False,
        'Court Start Time': None,
        'Court End': False,
        'Court End Time': None
    })

# Create rows for PM sessions
for index, row in grouped_pm.iterrows():
    data_list.append({
        'Court': row['Court'],
        'Session': 'PM',
        'M/H Label': row['Label'],
        'Remarks': '',
        'Officers Deployed': '',
        'Court Start': False,
        'Court Start Time': None,
        'Court End': False,
        'Court End Time': None
    })

# Convert the list of dictionaries to a DataFrame
df_template = pd.DataFrame(data_list, columns=columns)

# Load existing court status from database
def load_court_status():
    query = '''
    SELECT court, session, mh_label, remarks, officers_deployed, court_start, court_start_time, court_end, court_end_time
    FROM court_status WHERE date = %s;
    '''
    cursor.execute(query, (selected_date,))
    rows = cursor.fetchall()
    if rows:
        court_status_df = pd.DataFrame(rows, columns=['Court', 'Session', 'M/H Label', 'Remarks', 'Officers Deployed', 'Court Start', 'Court Start Time', 'Court End', 'Court End Time'])
        # Merge with df_template
        df_template_merged = df_template.merge(court_status_df, on=['Court', 'Session'], how='left', suffixes=('', '_db'))
        # Update columns if data exists in the database
        for col in ['M/H Label', 'Remarks', 'Officers Deployed', 'Court Start', 'Court Start Time', 'Court End', 'Court End Time']:
            df_template[col] = df_template_merged[col + '_db'].combine_first(df_template_merged[col])
    else:
        pass  # Use df_template as is

load_court_status()

total_courts = df_template.shape[0]

# 1. Display Court Status first (Combined AM and PM)
st.header("Court Status")

# Highlight the rows where the court has ended
def highlight_ended_rows(row):
    return ['background-color: red'] * len(row) if row['Court End'] else [''] * len(row)

# Display the DataFrame
st.dataframe(
    df_template.style.apply(highlight_ended_rows, axis=1),
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

# 4. Display Grouped PM Data (Include 'Time' and 'Hearing Type')
st.header("Grouped PM Data")
if not grouped_pm.empty:
    st.dataframe(
        grouped_pm[['Court', 'Label', 'Time', 'Hearing_Type', 'Accused']].style.hide(axis="index"),
        use_container_width=True
    )
else:
    st.write("No grouped PM data available.")

# 5. Display the assignments with editable functionality
# Separate Edit Remarks for AM and PM
st.header("Edit Remarks (AM)")

# Filter for AM sessions
df_am = df_template[df_template['Session'] == 'AM'].reset_index(drop=True)

# Define column configuration
column_config_am = {
    'Court': st.column_config.TextColumn('Court', disabled=True),
    'Session': st.column_config.TextColumn('Session', disabled=True),
    'M/H Label': st.column_config.TextColumn('M/H Label', disabled=True),
    'Remarks': st.column_config.TextColumn('Remarks', help='Enter any remarks or notes for the court session', width='large'),
    'Officers Deployed': st.column_config.TextColumn('Officers Deployed', help='Enter officers deployed', width='large'),
    'Court Start': st.column_config.CheckboxColumn('Court Start', help='Indicate if the court session has started', width='small'),
    'Court Start Time': st.column_config.TimeColumn('Court Start Time', help='Time when court started'),
    'Court End': st.column_config.CheckboxColumn('Court End', help='Indicate if the court session has ended', width='small'),
    'Court End Time': st.column_config.TimeColumn('Court End Time', help='Time when court ended'),
}

# Display the data editor for AM sessions
edited_assignments_am = st.data_editor(
    df_am,
    column_config=column_config_am,
    hide_index=True,
    use_container_width=True,
    num_rows='dynamic',
    key='data_editor_am'
)

st.header("Edit Remarks (PM)")

# Filter for PM sessions
df_pm = df_template[df_template['Session'] == 'PM'].reset_index(drop=True)

# Define column configuration for PM (same as AM)
column_config_pm = column_config_am

# Display the data editor for PM sessions
edited_assignments_pm = st.data_editor(
    df_pm,
    column_config=column_config_pm,
    hide_index=True,
    use_container_width=True,
    num_rows='dynamic',
    key='data_editor_pm'
)

# Combine edited data back into df_template
df_template_updated = pd.concat([edited_assignments_am, edited_assignments_pm], ignore_index=True)

# Capture current time when 'Court Start' or 'Court End' is checked
for idx, row in df_template_updated.iterrows():
    if row['Court Start'] and pd.isnull(row['Court Start Time']):
        df_template_updated.at[idx, 'Court Start Time'] = datetime.now().time()
    if row['Court End'] and pd.isnull(row['Court End Time']):
        df_template_updated.at[idx, 'Court End Time'] = datetime.now().time()

# Update the court_status table with the edited data
try:
    for index, row in df_template_updated.iterrows():
        # Upsert the data into court_status table
        upsert_query = '''
        INSERT INTO court_status (date, court, session, mh_label, remarks, officers_deployed, court_start, court_start_time, court_end, court_end_time, last_updated)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (date, court, session) DO UPDATE SET
            mh_label = EXCLUDED.mh_label,
            remarks = EXCLUDED.remarks,
            officers_deployed = EXCLUDED.officers_deployed,
            court_start = EXCLUDED.court_start,
            court_start_time = EXCLUDED.court_start_time,
            court_end = EXCLUDED.court_end,
            court_end_time = EXCLUDED.court_end_time,
            last_updated = NOW();
        '''
        cursor.execute(upsert_query, (
            selected_date, row['Court'], row['Session'], row['M/H Label'], row['Remarks'], row['Officers Deployed'],
            row['Court Start'], row['Court Start Time'], row['Court End'], row['Court End Time']
        ))
    conn.commit()
    st.success("Court status updated in the database.")
except Exception as e:
    conn.rollback()
    st.error(f"Error updating court status in database: {e}")

# Update df_template with the latest data
df_template = df_template_updated.copy()

# 6. Display the general remarks text area
st.header("General Remarks")
general_remarks = st.text_area(
    "Enter your general remarks or notes here:",
    value="",
    height=150
)

# 7. Export Functionality
st.header("Export Data to Excel")

# Get the list of columns from the DataFrame
all_columns = list(df_template.columns)

# Let the user select columns to export
selected_columns_am = st.multiselect(
    "Select columns to export for AM",
    options=all_columns + ['General Remarks'],  # Include 'General Remarks' as an option
    default=all_columns,
    key='export_columns_am'
)

selected_columns_pm = st.multiselect(
    "Select columns to export for PM",
    options=all_columns + ['General Remarks'],  # Include 'General Remarks' as an option
    default=all_columns,
    key='export_columns_pm'
)

# Button to export data
if st.button("Export to Excel"):
    # Create a BytesIO buffer
    output = BytesIO()
    # Write the DataFrame to the buffer
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        # Prepare the DataFrames for export
        export_df_am = df_template[df_template['Session'] == 'AM'][selected_columns_am].copy()
        export_df_pm = df_template[df_template['Session'] == 'PM'][selected_columns_pm].copy()
        # If 'General Remarks' is selected, add it to the DataFrame
        if 'General Remarks' in selected_columns_am:
            export_df_am['General Remarks'] = general_remarks
        if 'General Remarks' in selected_columns_pm:
            export_df_pm['General Remarks'] = general_remarks
        # Write to separate sheets
        export_df_am.to_excel(writer, index=False, sheet_name='Edit Remarks AM')
        export_df_pm.to_excel(writer, index=False, sheet_name='Edit Remarks PM')
    # Set the buffer position to the beginning
    output.seek(0)
    # Create a download button
    st.download_button(
        label="Download Excel File",
        data=output,
        file_name=f"Court_Session_Notes_{date_str}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

# ====================== Officer Management Section ======================

st.header("Officer Management")

# Function to load officers from the database
def load_officers():
    query = '''
    SELECT OfficerID, OfficerName, Team, Intake, Status, Availability, TimeSensitive
    FROM Officers
    ORDER BY OfficerID;
    '''
    cursor.execute(query)
    rows = cursor.fetchall()
    if rows:
        officers_df = pd.DataFrame(rows, columns=['OfficerID', 'OfficerName', 'Team', 'Intake', 'Status', 'Availability', 'TimeSensitive'])
    else:
        officers_df = pd.DataFrame(columns=['OfficerID', 'OfficerName', 'Team', 'Intake', 'Status', 'Availability', 'TimeSensitive'])
    return officers_df

officers_df = load_officers()

# Display the officers table with editing capabilities
st.subheader("Current Officers")

# Define column configuration for officers
officer_column_config = {
    'OfficerID': st.column_config.TextColumn('ID', disabled=True),
    'OfficerName': st.column_config.TextColumn('Officer Name', required=True),
    'Team': st.column_config.TextColumn('Team', required=True),
    'Intake': st.column_config.NumberColumn('Intake', min_value=0, required=False),
    'Status': st.column_config.SelectboxColumn(
        'Status',
        options=['Regular', 'SC', 'Freshie'],
        required=True
    ),
    'Availability': st.column_config.SelectboxColumn(
        'Availability',
        options=['Available', 'Non Available'],
        required=True
    ),
    'TimeSensitive': st.column_config.CheckboxColumn('Time Sensitive'),
}

# Display the data editor for officers
edited_officers = st.data_editor(
    officers_df,
    column_config=officer_column_config,
    hide_index=True,
    use_container_width=True,
    num_rows='dynamic',
    key='data_editor_officers'
)

# Button to update officers in the database
if st.button("Update Officers"):
    try:
        for index, row in edited_officers.iterrows():
            if pd.isnull(row['OfficerID']):
                # Insert new officer
                insert_query = '''
                INSERT INTO Officers (OfficerName, Team, Intake, Status, Availability, TimeSensitive)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (OfficerName) DO NOTHING;
                '''
                cursor.execute(insert_query, (
                    row['OfficerName'],
                    row['Team'],
                    int(row['Intake']) if not pd.isnull(row['Intake']) else None,
                    row['Status'],
                    row['Availability'],
                    row['TimeSensitive'] if not pd.isnull(row['TimeSensitive']) else False
                ))
            else:
                # Update existing officer
                update_query = '''
                UPDATE Officers
                SET OfficerName = %s,
                    Team = %s,
                    Intake = %s,
                    Status = %s,
                    Availability = %s,
                    TimeSensitive = %s
                WHERE OfficerID = %s;
                '''
                cursor.execute(update_query, (
                    row['OfficerName'],
                    row['Team'],
                    int(row['Intake']) if not pd.isnull(row['Intake']) else None,
                    row['Status'],
                    row['Availability'],
                    row['TimeSensitive'] if not pd.isnull(row['TimeSensitive']) else False,
                    row['OfficerID']
                ))
        conn.commit()
        st.success("Officers updated successfully.")
    except Exception as e:
        conn.rollback()
        st.error(f"Error updating officers: {e}")

# Button to delete selected officers
st.subheader("Delete Officers")

# Allow user to select officers to delete
officer_ids = officers_df['OfficerID'].tolist()
selected_officers = st.multiselect(
    "Select officers to delete",
    options=officer_ids,
    format_func=lambda x: f"ID {x}: " + officers_df.loc[officers_df['OfficerID'] == x, 'OfficerName'].values[0] if x in officers_df['OfficerID'].values else x
)

if st.button("Delete Selected Officers"):
    if selected_officers:
        try:
            delete_query = sql.SQL("DELETE FROM Officers WHERE OfficerID IN ({ids})").format(
                ids=sql.SQL(',').join(map(sql.Literal, selected_officers))
            )
            cursor.execute(delete_query)
            conn.commit()
            st.success("Selected officers have been deleted.")
            # Reload the officers dataframe
            officers_df = load_officers()
        except Exception as e:
            conn.rollback()
            st.error(f"Error deleting officers: {e}")
    else:
        st.warning("No officers selected for deletion.")



if st.button("Close Database Connection"):
    try:
        cursor.close()
        conn.close()
        st.success("Database connection closed.")
    except Exception as e:
        st.error(f"Error closing connection: {e}")
              
