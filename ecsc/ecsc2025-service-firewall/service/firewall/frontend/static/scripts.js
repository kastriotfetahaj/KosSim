async function apiRequest(method, url, data = null) {
    const options = {
        method: method,
        headers: {
            'Content-Type': 'application/json'
        }
    };

    if (method === 'POST' || method === 'PUT') {
        options.body = JSON.stringify(data);
    } else if (data) {
        // For GET requests, serialize the data in the URL as a query parameter
        const params = new URLSearchParams(data).toString();
        url += `?${params}`;
    }

    const response = await fetch(url, options);
    if (!response.ok) {
        const error = await response.json();  // Extract the error message from the response
        if (error.validation_error) {
            const validationErrors = getValidationErrors(error.validation_error);
            throw new Error(validationErrors.join("\n"));
        } else {
            // Handle custom SNMPException or other HTTP exceptions
            throw new Error(`${error.description} (Code: ${error.code}, Name: ${error.name})`);
        }
    }
    return await response.json();
}

function getValidationErrors(validationError) {
    const errors = [];
    Object.keys(validationError).forEach(key => {
        validationError[key].forEach(err => {
            errors.push(`${err.msg} (Input: ${err.input})`);
        });
    });
    return errors;
}

function advancedGet() {
    const input = document.getElementById('advanced-get-input').value;
    apiRequest('GET', 'api/advanced', { data: input }).then(response => {
        document.getElementById('advanced-result').innerText = response.value;
        document.getElementById('advanced-result').classList.remove('error');
    }).catch(error => {
        console.error('Error:', error.message);
        document.getElementById('advanced-result').innerText = `${error.message}`;
        document.getElementById('advanced-result').classList.add('error');
    });
}

function customGet() {
    const identifier = document.getElementById('custom-get-identifier').value;
    const secret = document.getElementById('custom-get-secret').value;
    var data = { secret: secret };
    if (identifier) {
        data.identifier = identifier;
    }
    apiRequest('GET', 'api/custom', data).then(response => {
        const value = atob(response.value);
        document.getElementById('custom-get-result-identifier').innerText = `${response.identifier}`;
        document.getElementById('custom-get-result-identifier').classList.remove('error');
        document.getElementById('custom-get-result').innerText = `${value}`;
        document.getElementById('custom-get-result').classList.remove('error');
    }).catch(error => {
        console.error('Error:', error.message);
        document.getElementById('custom-get-result-identifier').innerText = 'None';
        document.getElementById('custom-get-result-identifier').classList.add('error');
        document.getElementById('custom-get-result').innerText = `${error.message}`;
        document.getElementById('custom-get-result').classList.add('error');
    });
}

function customPost() {
    const secret = document.getElementById('custom-post-secret').value;
    const value = document.getElementById('custom-post-value').value;
    apiRequest('POST', 'api/custom', { secret: secret, value: btoa(value) }).then(response => {
        const value = atob(response.value);
        document.getElementById('custom-post-result-identifier').innerText = `${response.identifier}`;
        document.getElementById('custom-post-result-identifier').classList.remove('error');
        document.getElementById('custom-post-result').innerText = `${value}`;
        document.getElementById('custom-post-result').classList.remove('error');
    }).catch(error => {
        console.error('Error:', error.message);
        document.getElementById('custom-post-result-identifier').innerText = 'None';
        document.getElementById('custom-post-result-identifier').classList.add('error');
        document.getElementById('custom-post-result').innerText = `${error.message}`;
        document.getElementById('custom-post-result').classList.add('error');
    });
}

async function genericInit(init_path, update_path) {
    try {
        const response = await apiRequest('GET', init_path);
        const tbody = document.getElementById('monitoring-entries');
        tbody.innerHTML = '';  // Clear previous rows
        Object.entries(response.values).forEach(([label, value]) => {
            const row = document.createElement('tr');
            const labelCell = document.createElement('td');
            const valueCell = document.createElement('td');
            const actionCell = document.createElement('td');
            const valueTextNode = document.createTextNode(value);
            const labelTextNode = document.createTextNode(label);

            const refreshButton = document.createElement('button');
            refreshButton.innerText = 'Refresh';
            refreshButton.onclick = () => {
                apiRequest('GET', update_path, { label }).then(response => {
                    var value = response.value;
                    if (value === null) {
                        value = 'null';
                        valueCell.classList.add('null-value');
                    } else {
                        valueCell.classList.remove('null-value');
                    }
                    valueCell.innerText = value;
                }).catch(error => {
                    console.error('Error:', error.message);
                    valueCell.innerText = `Error: ${error.message}`;
                });
            };

            labelCell.appendChild(labelTextNode);
            valueCell.appendChild(valueTextNode);
            actionCell.appendChild(refreshButton);
            row.appendChild(labelCell);
            row.appendChild(valueCell);
            row.appendChild(actionCell);
            tbody.appendChild(row);
        });
    } catch (error) {
        console.error('Error:', error.message);
        document.getElementById('monitoring-init-result').innerText = `Error: ${error.message}`;
    }
}

async function monitoringInit() {
    await genericInit('api/monitoring_init', 'api/monitoring')
}

async function userMonitoringInit() {
    await genericInit('api/monitoring_user_init', 'api/monitoring_user')
}
