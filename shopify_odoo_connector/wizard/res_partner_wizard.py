# -*- coding: utf-8 -*-
################################################################################
#
#    Cybrosys Technologies Pvt. Ltd.
#
#    Copyright (C) 2021-TODAY Cybrosys Technologies(<https://www.cybrosys.com>).
#    Author: Cybrosys Techno Solutions (Contact : odoo@cybrosys.com)
#
#    This program is under the terms of the Odoo Proprietary License v1.0
#    (OPL-1)
#    It is forbidden to publish, distribute, sublicense, or sell copies of the
#    Software or modified copies of the Software.
#
#    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
#    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
#    IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM,
#    DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
#    OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE
#    USE OR OTHER DEALINGS IN THE SOFTWARE.
#
################################################################################
import re
from odoo import models, fields
import requests
import json
from odoo.exceptions import ValidationError


class CustomerWizard(models.TransientModel):
    _name = 'customer.wizard'
    _description = 'Customer Wizard'

    import_customers = fields.Selection(string='Import/Export',
                                        selection=[('shopify', 'To Shopify'),
                                                   ('odoo', 'From Shopify')],
                                        required=True, default='odoo')
    shopify_instance_id = fields.Many2one('shopify.configuration',
                                          string="Shopify Instance",
                                          required=True)

    def sync_customers(self):
        """
        Method for sync customers in shopify.
        """
        shopify_instance = self.shopify_instance_id
        api_key = self.shopify_instance_id.con_endpoint
        password = self.shopify_instance_id.consumer_key
        store_name = self.shopify_instance_id.shop_name
        version = self.shopify_instance_id.version
        if self.import_customers == 'shopify' and not self.shopify_instance_id.import_customer:
            raise ValidationError('For Syncing Customers to Shopify Enable Export Customers option in shopify configuration ')
        else:
            if self.import_customers == 'shopify':
                customer_url = "https://%s:%s@%s/admin/api/%s/customers.json" % (
                    api_key, password, store_name, version)
                partner = self.env['res.partner'].search(
                    [('company_id', 'in', [False, shopify_instance.company_id.id]), ('type', '=', 'contact')])
                for customer in partner:
                    instance_ids = customer.shopify_sync_ids.mapped(
                        'instance_id.id')
                    if self.shopify_instance_id.id not in instance_ids:
                        payload = json.dumps({
                            "customer": {
                                "first_name": customer.name,
                                "last_name": "",
                                "email": customer.email or '',
                                "verified_email": True,
                                "addresses": [
                                    {
                                        "address1": customer.street,
                                        "city": customer.city,
                                        "province": customer.state_id.name or '',
                                        "zip": customer.zip,
                                        "last_name": "",
                                        "first_name": customer.name,
                                        "country": customer.country_id.name or ''
                                    }
                                ],
                                "send_email_invite": True
                            }
                        })
                        headers = {
                            'Content-Type': 'application/json'
                        }
                        response = requests.request("POST", customer_url,
                                                    headers=headers,
                                                    data=payload)
                        if response.status_code == 201:
                            response_rec = response.json()
                            response_customer_id = response_rec['customer'][
                                'id']
                            customer.shopify_sync_ids.sudo().create({
                                'instance_id': self.shopify_instance_id.id,
                                'shopify_customer_id': response_customer_id,
                                'customer_id': customer.id,
                            })
            else:
                customer_url = "https://%s:%s@%s/admin/api/%s/customers.json" % (
                    api_key, password, store_name, version)
                payload = []
                headers = {
                    'Content-Type': 'application/json'
                }
                response = requests.request("GET", customer_url,
                                            headers=headers,
                                            data=payload)
                j = response.json()
                shopify_customers = j['customers']
                customer_link = response.headers[
                    'link'] if 'link' in response.headers else ''
                customer_links = customer_link.split(',')
                for link in customer_links:
                    match = re.compile(r'rel=\"next\"').search(link)
                    if match:
                        customer_link = link
                rel = re.search('rel=\"(.*)\"', customer_link).group(
                    1) if 'link' in response.headers else ''
                if customer_link and rel == 'next':
                    i = 0
                    n = 1
                    while i < n:
                        page_info = re.search('page_info=(.*)>',
                                              customer_link).group(1)
                        limit = re.search('limit=(.*)&', customer_link).group(1)
                        customer_link = "https://%s:%s@%s/admin/api/%s/customers.json?limit=%s&page_info=%s" % (
                            api_key, password, store_name, version, limit,
                            page_info)
                        response = requests.request('GET', customer_link,
                                                    headers=headers, data=payload)
                        j = response.json()
                        customers = j['customers']
                        shopify_customers += customers
                        customer_link = response.headers['link']
                        customer_links = customer_link.split(',')
                        for link in customer_links:
                            match = re.compile(r'rel=\"next\"').search(link)
                            if match:
                                customer_link = link
                        rel = re.search('rel=\"next\"', customer_link)
                        i += 1
                        if customer_link and rel is not None:
                            n += 1
                for customer in shopify_customers:
                    exist_customers = self.env['res.partner'].search(
                        [('shopify_customer_id', '=', customer['id']),
                         ('shopify_instance_id', '=', shopify_instance.id)])
                    if not exist_customers:
                        vals = {}
                        if customer['addresses']:
                            country_id = self.env['res.country'].sudo().search([
                                ('name', '=', customer['addresses'][0]['country'])
                            ])
                            state_id = self.env['res.country.state'].sudo().search([
                                ('name', '=', customer['addresses'][0]['province'])
                            ])
                            vals = {
                                'street': customer['addresses'][0]['address1'],
                                'street2': customer['addresses'][0]['address2'],
                                'city': customer['addresses'][0]['city'],
                                'country_id': country_id.id if country_id else False,
                                'state_id': state_id.id if state_id else False,
                                'zip': customer['addresses'][0]['zip'],
                            }
                        if customer['first_name']:
                            vals['name'] = customer['first_name']
                        if customer['last_name']:
                            if customer['first_name']:
                                vals['name'] = customer['first_name'] + ' ' + \
                                               customer['last_name']
                            else:
                                vals['name'] = customer['last_name']
                        if not customer['first_name'] and not customer['last_name'] and customer['email']:
                            vals['name'] = customer['email']
                        vals['email'] = customer['email']
                        vals['phone'] = customer['phone']
                        vals['shopify_customer_id'] = customer['id']
                        vals['shopify_instance_id'] = shopify_instance.id
                        vals['synced_customer'] = True
                        vals['company_id'] = shopify_instance.company_id.id
                        if customer['first_name']:
                            new_customer = self.env['res.partner'].sudo().create(vals)
                            new_customer.shopify_sync_ids.sudo().create({
                                'instance_id': self.shopify_instance_id.id,
                                'shopify_customer_id': customer['id'],
                                'customer_id': new_customer.id,
                            })
                        else:
                            self.env['log.message'].sudo().create({
                                'name': 'Customer Creation not processed for shopify id : ' + str(customer['id']),
                                'shopify_instance_id': self.shopify_instance_id.id,
                                'model': 'res.partner',
                            })
                    else:
                        vals = {}
                        if customer['addresses']:
                            country_id = self.env['res.country'].sudo().search([
                                ('name', '=', customer['addresses'][0]['country'])
                            ])
                            state_id = self.env['res.country.state'].sudo().search([
                                ('name', '=', customer['addresses'][0]['province'])
                            ])
                            vals = {
                                'street': customer['addresses'][0]['address1'],
                                'street2': customer['addresses'][0]['address2'],
                                'city': customer['addresses'][0]['city'],
                                'country_id': country_id.id if country_id else False,
                                'state_id': state_id.id if state_id else False,
                                'zip': customer['addresses'][0]['zip'],
                            }
                        if customer['first_name']:
                            vals['name'] = customer['first_name']
                        if customer['last_name']:
                            if customer['first_name']:
                                vals['name'] = customer['first_name'] + ' ' + \
                                               customer['last_name']
                        if not customer['first_name'] and not customer['last_name'] and customer['email']:
                            vals['name'] = customer['email']
                        vals['email'] = customer['email']
                        vals['phone'] = customer['phone']
                        vals['shopify_customer_id'] = customer['id']
                        vals['shopify_instance_id'] = shopify_instance.id
                        vals['synced_customer'] = True
                        vals['company_id'] = shopify_instance.company_id.id
                        self.env['res.partner'].sudo().write(vals)
