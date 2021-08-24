# Copyright (c) 2021, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe import _
from frappe.desk.form import assign_to
from frappe.model.document import Document
from frappe.utils import flt, unique

class EmployeeBoardingController(Document):
	'''
		Create the project and the task for the boarding process
		Assign to the concerned person and roles as per the onboarding/separation template
	'''
	def validate(self):
		# remove the task if linked before submitting the form
		if self.amended_from:
			for activity in self.activities:
				activity.task = ''

	def on_submit(self):
		# create the project for the given employee onboarding
		project_name = _(self.doctype) + ' : '
		if self.doctype == 'Employee Onboarding':
			project_name += self.job_applicant
		else:
			project_name += self.employee

		project = frappe.get_doc({
				'doctype': 'Project',
				'project_name': project_name,
				'expected_start_date': self.date_of_joining if self.doctype == 'Employee Onboarding' else self.resignation_letter_date,
				'department': self.department,
				'company': self.company
			}).insert(ignore_permissions=True, ignore_mandatory=True)

		self.db_set('project', project.name)
		self.db_set('boarding_status', 'Pending')
		self.reload()
		self.create_task_and_notify_user()

	def create_task_and_notify_user(self):
		# create the task for the given project and assign to the concerned person
		for activity in self.activities:
			if activity.task:
				continue

			task = frappe.get_doc({
				'doctype': 'Task',
				'project': self.project,
				'subject': activity.activity_name + ' : ' + self.employee_name,
				'description': activity.description,
				'department': self.department,
				'company': self.company,
				'task_weight': activity.task_weight
			}).insert(ignore_permissions=True)
			activity.db_set('task', task.name)

			users = [activity.user] if activity.user else []
			if activity.role:
				user_list = frappe.db.sql_list('''
					SELECT
						DISTINCT(has_role.parent)
					FROM
						`tabHas Role` has_role
							LEFT JOIN `tabUser` user
								ON has_role.parent = user.name
					WHERE
						has_role.parenttype = 'User'
							AND user.enabled = 1
							AND has_role.role = %s
				''', activity.role)
				users = unique(users + user_list)

				if 'Administrator' in users:
					users.remove('Administrator')

			# assign the task the users
			if users:
				self.assign_task_to_users(task, users)

	def assign_task_to_users(self, task, users):
		for user in users:
			args = {
				'assign_to': [user],
				'doctype': task.doctype,
				'name': task.name,
				'description': task.description or task.subject,
				'notify': self.notify_users_by_email
			}
			assign_to.add(args)

	def on_cancel(self):
		# delete task project
		for task in frappe.get_all('Task', filters={'project': self.project}):
			frappe.delete_doc('Task', task.name, force=1)
		frappe.delete_doc('Project', self.project, force=1)
		self.db_set('project', '')
		for activity in self.activities:
			activity.db_set('task', '')


@frappe.whitelist()
def get_onboarding_details(parent, parenttype):
	return frappe.get_all('Employee Boarding Activity',
		fields=['activity_name', 'role', 'user', 'required_for_employee_creation', 'description', 'task_weight'],
		filters={'parent': parent, 'parenttype': parenttype},
		order_by= 'idx')


def update_employee_boarding_status(project):
	employee_onboarding = frappe.db.exists('Employee Onboarding', {'project': project.name})
	employee_separation = frappe.db.exists('Employee Separation', {'project': project.name})

	if not (employee_onboarding or employee_separation):
		return

	status = 'Pending'
	if flt(project.percent_complete) > 0.0 and flt(project.percent_complete) < 100.0:
		status = 'In Process'
	elif flt(project.percent_complete) == 100.0:
		status = 'Completed'

	if employee_onboarding:
		frappe.db.set_value('Employee Onboarding', employee_onboarding, 'boarding_status', status)
	elif employee_separation:
		frappe.db.set_value('Employee Separation', employee_separation, 'boarding_status', status)
